"""
Sign in with Google / Apple (Stage 28) -- standard OpenID Connect,
authorization-code flow with PKCE, handled entirely on the server.

Nothing here is active until the provider's credentials exist in the
environment (see docs/stage28/PROVIDER_SETUP.md); with none set,
configured_providers() is empty and the login page shows no provider
buttons. No secret is ever written to the repository.

PyJWT is imported lazily so the app still boots without it.
"""

import base64
import hashlib
import os
import secrets
import time
from urllib.parse import urlencode

import httpx

import database

PROVIDERS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "jwks": "https://www.googleapis.com/oauth2/v3/certs",
        "issuers": ("https://accounts.google.com", "accounts.google.com"),
        "scope": "openid email profile",
        "algorithms": ["RS256"],
    },
    "apple": {
        "authorize": "https://appleid.apple.com/auth/authorize",
        "token": "https://appleid.apple.com/auth/token",
        "jwks": "https://appleid.apple.com/auth/keys",
        "issuers": ("https://appleid.apple.com",),
        "scope": "name email",
        "algorithms": ["RS256"],
    },
}


class OAuthError(Exception):
    """Carries a short, generic code that is safe to show the browser."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _env(name):
    return os.environ.get(name, "").strip()


def public_api_base():
    return _env("PUBLIC_API_BASE").rstrip("/")


def redirect_uri(provider):
    return f"{public_api_base()}/auth/{provider}/callback"


def client_id(provider):
    return _env("GOOGLE_CLIENT_ID" if provider == "google" else "APPLE_CLIENT_ID")


def is_configured(provider):
    if provider not in PROVIDERS or not public_api_base():
        return False
    try:
        import jwt  # noqa: F401
    except ImportError:
        return False
    if provider == "google":
        return bool(_env("GOOGLE_CLIENT_ID") and _env("GOOGLE_CLIENT_SECRET"))
    return bool(_env("APPLE_CLIENT_ID") and _env("APPLE_TEAM_ID")
                and _env("APPLE_KEY_ID") and _env("APPLE_PRIVATE_KEY"))


def configured_providers():
    return {p: is_configured(p) for p in PROVIDERS}


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def build_authorize_url(provider):
    """Create the server-side flow record and return the provider URL."""
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    database.save_oauth_flow(state, provider, nonce, verifier)
    params = {
        "client_id": client_id(provider),
        "redirect_uri": redirect_uri(provider),
        "response_type": "code",
        "scope": PROVIDERS[provider]["scope"],
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if provider == "apple":
        params["response_mode"] = "form_post"  # needed when asking for name/email
    return PROVIDERS[provider]["authorize"] + "?" + urlencode(params)


def _apple_client_secret():
    import jwt
    now = int(time.time())
    key = _env("APPLE_PRIVATE_KEY").replace("\\n", "\n")
    return jwt.encode(
        {"iss": _env("APPLE_TEAM_ID"), "iat": now, "exp": now + 300,
         "aud": "https://appleid.apple.com", "sub": _env("APPLE_CLIENT_ID")},
        key, algorithm="ES256", headers={"kid": _env("APPLE_KEY_ID")})


# --- the only two functions that touch the network (mocked in tests) -------

def _post_token(provider, code, code_verifier):
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(provider),
        "client_id": client_id(provider),
        "code_verifier": code_verifier,
        "client_secret": _env("GOOGLE_CLIENT_SECRET") if provider == "google"
        else _apple_client_secret(),
    }
    r = httpx.post(PROVIDERS[provider]["token"], data=data, timeout=10)
    r.raise_for_status()
    return r.json()


def _fetch_jwks(provider):
    r = httpx.get(PROVIDERS[provider]["jwks"], timeout=10)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------

def verify_id_token(provider, id_token, nonce):
    """Check signature, issuer, audience, expiry and nonce. Returns claims."""
    import jwt
    cfg = PROVIDERS[provider]
    try:
        header = jwt.get_unverified_header(id_token)
        keys = _fetch_jwks(provider).get("keys", [])
        jwk = next((k for k in keys if k.get("kid") == header.get("kid")), None)
        if jwk is None or header.get("alg") not in cfg["algorithms"]:
            raise OAuthError("provider_error")
        key = jwt.PyJWK(jwk).key
        claims = jwt.decode(
            id_token, key, algorithms=cfg["algorithms"],
            audience=client_id(provider),
            options={"require": ["exp", "iss", "aud", "sub"]})
    except OAuthError:
        raise
    except Exception:
        raise OAuthError("provider_error")
    if claims.get("iss") not in cfg["issuers"]:
        raise OAuthError("provider_error")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OAuthError("provider_error")
    return claims


def _truthy(v):
    return v is True or str(v).lower() == "true"


def complete_sign_in(provider, state, code):
    """
    Finish a callback. Returns ("login"|"link", ticket). Never merges two
    accounts on an email match: a match only produces a 'link' ticket,
    which the browser must redeem with the existing account's password.
    """
    if provider not in PROVIDERS or not state or not code:
        raise OAuthError("invalid_request")
    flow = database.pop_oauth_flow(state)
    if not flow or flow["provider"] != provider:
        raise OAuthError("invalid_request")
    try:
        tokens = _post_token(provider, code, flow["code_verifier"])
    except Exception:
        raise OAuthError("provider_error")
    id_token = tokens.get("id_token")
    if not id_token:
        raise OAuthError("provider_error")
    claims = verify_id_token(provider, id_token, flow["nonce"])

    subject = str(claims["sub"])
    email = (claims.get("email") or "").strip().lower()
    verified = bool(email) and _truthy(claims.get("email_verified"))

    identity = database.find_identity(provider, subject)
    if identity:
        return "login", database.create_oauth_ticket("login", user_id=identity["user_id"])

    existing = database.find_user_by_email(email) if email else None
    if existing:
        if not verified:
            raise OAuthError("email_unverified")
        return "link", database.create_oauth_ticket(
            "link", user_id=existing["id"], provider=provider, subject=subject, email=email)

    user_id = database.create_user_from_identity(
        provider, subject, email if verified else None,
        email or claims.get("name") or "dreamer")
    return "login", database.create_oauth_ticket("login", user_id=user_id)
