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
import re
import hmac
import os
import secrets
import time
from urllib.parse import urlencode, urlparse

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
    """Carries a short, generic code that is safe to show the browser, and
    what the flow was for (so a failed deletion check isn't shown as a failed login)."""

    def __init__(self, code, purpose="login"):
        super().__init__(code)
        self.code = code
        self.purpose = purpose


def _env(name):
    return os.environ.get(name, "").strip()


def public_api_base():
    return _env("PUBLIC_API_BASE").rstrip("/")


def frontend_url():
    """Where the browser is sent back to. Fixed by configuration, never by the request."""
    return _env("FRONTEND_URL").rstrip("/")


def redirect_uri(provider):
    return f"{public_api_base()}/auth/{provider}/callback"


def client_id(provider):
    return _env("GOOGLE_CLIENT_ID" if provider == "google" else "APPLE_CLIENT_ID")


def _is_local(url):
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")


def _url_problem(name, url):
    u = urlparse(url)
    if not url or not u.scheme or not u.netloc:
        return f"{name} is not set to a full URL"
    if u.scheme != "https" and not (u.scheme == "http" and _is_local(url)):
        return f"{name} must use https (http is allowed only for localhost)"
    if u.query or u.fragment:
        return f"{name} must not contain a query or fragment"
    return None


def config_problems(provider):
    """Names what is wrong with the configuration (never any values)."""
    if provider not in PROVIDERS:
        return ["unknown provider"]
    problems = []
    try:
        import jwt  # noqa: F401
    except ImportError:
        problems.append("PyJWT is not installed")
    for name, url in (("PUBLIC_API_BASE", public_api_base()), ("FRONTEND_URL", frontend_url())):
        p = _url_problem(name, url)
        if p:
            problems.append(p)
    if provider == "google":
        for var in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
            if not _env(var):
                problems.append(f"{var} is not set")
    else:
        for var in ("APPLE_CLIENT_ID", "APPLE_TEAM_ID", "APPLE_KEY_ID", "APPLE_PRIVATE_KEY"):
            if not _env(var):
                problems.append(f"{var} is not set")
    return problems


def is_configured(provider):
    return not config_problems(provider)


def configured_providers():
    return {p: is_configured(p) for p in PROVIDERS}


def secure_cookies():
    """The binding cookie is Secure whenever the backend is served over https."""
    return public_api_base().startswith("https://")


def startup_report():
    """One log line at boot: which providers are on and, if a provider is
    partly configured, what is missing (names only, never values)."""
    import observability
    for p in PROVIDERS:
        probs = config_problems(p)
        started = any(_env(v) for v in (
            ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET") if p == "google"
            else ("APPLE_CLIENT_ID", "APPLE_TEAM_ID", "APPLE_KEY_ID", "APPLE_PRIVATE_KEY")))
        if not probs:
            observability.log_event("oauth_config", provider=p, enabled=True)
        elif started:
            observability.log_event("oauth_config", provider=p, enabled=False, problems=probs)


# --- browser binding -------------------------------------------------------

def binding_cookie_name(state):
    """One cookie per in-flight sign-in, so two tabs can't clobber each other."""
    return "loom_oauth_" + hashlib.sha256(state.encode()).hexdigest()[:16]


def _hash_binding(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def build_authorize_url(provider, purpose="login", user_id=None):
    """
    Create the server-side flow record and return (provider URL, state,
    binding secret). The binding secret goes to the browser in an HttpOnly
    cookie; only its hash is stored, so the callback can prove it is arriving
    in the browser that started the sign-in.
    """
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    binding = secrets.token_urlsafe(32)
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    database.save_oauth_flow(state, provider, nonce, verifier, _hash_binding(binding),
                             purpose=purpose, user_id=user_id)
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
    if purpose == "delete":
        params["prompt"] = "login"          # make Google ask again, not reuse the session silently
        params["max_age"] = "0"
    if provider == "apple":
        params["response_mode"] = "form_post"  # needed when asking for name/email
    return PROVIDERS[provider]["authorize"] + "?" + urlencode(params), state, binding


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


def _claim_flow(provider, state, binding_cookie):
    """
    Consume the flow (single use, atomic) and check it belongs to this
    provider and to the browser presenting it. A callback that fails any
    check still burns the flow, so it can't be retried.
    """
    if provider not in PROVIDERS or not state:
        raise OAuthError("invalid_request")
    flow = database.pop_oauth_flow(state)
    if not flow or flow["provider"] != provider:
        raise OAuthError("invalid_request")
    if not binding_cookie or not flow.get("binding_hash") or not hmac.compare_digest(
            _hash_binding(binding_cookie), flow["binding_hash"]):
        raise OAuthError("invalid_request")
    return flow


def purpose_of_cancelled(provider, state, binding_cookie):
    """The person pressed Cancel at the provider: confirm the callback is
    genuine, consume the flow, and say what it was for."""
    return _claim_flow(provider, state, binding_cookie)["purpose"]


_ERR_CODE = re.compile(r"^[a-z_]{1,40}$")
REAUTH_MAX_AGE_SECONDS = 300      # how recent Google's own sign-in must be for a deletion proof
REAUTH_CLOCK_SKEW_SECONDS = 60


def _log_token_failure(provider, exc):
    """
    Say *why* the code exchange failed without leaking anything: only the HTTP
    status and the provider's short `error` code (e.g. invalid_client,
    invalid_grant, redirect_uri_mismatch) when it is a plain lowercase token.
    Never the description, request, code, client secret or response body.
    """
    import observability
    status, code = None, type(exc).__name__
    resp = getattr(exc, "response", None)
    if resp is not None:
        status = getattr(resp, "status_code", None)
        try:
            err = resp.json().get("error")
            code = err if isinstance(err, str) and _ERR_CODE.match(err) else f"http_{status}"
        except Exception:
            code = f"http_{status}"
    observability.log_event("oauth_token_exchange_failed", provider=provider, http_status=status, error=code)


def _reauth_is_fresh(claims):
    """
    For deletion we asked Google for prompt=login&max_age=0. If Google reports
    when the person actually authenticated (auth_time), it must be recent.
    Whether the claim is present is logged (a boolean) so a live test shows what
    real Google sends; an absent claim is accepted because the request itself
    already demanded a fresh login and some providers omit the claim.
    """
    import observability
    auth_time = claims.get("auth_time")
    observability.log_event("oauth_reauth_check", auth_time_present=auth_time is not None)
    if auth_time is None:
        return True
    try:
        age = time.time() - float(auth_time)
    except (TypeError, ValueError):
        return False
    return -REAUTH_CLOCK_SKEW_SECONDS <= age <= REAUTH_MAX_AGE_SECONDS


def complete_sign_in(provider, state, code, binding_cookie):
    """
    Finish a callback. Returns (kind, ticket) where kind is "login", "link"
    or "reauth". Never merges two accounts on an email match: a match only
    produces a 'link' ticket, which the browser must redeem with the existing
    account's password.
    """
    if not code:
        raise OAuthError("invalid_request")
    flow = _claim_flow(provider, state, binding_cookie)
    try:
        tokens = _post_token(provider, code, flow["code_verifier"])
    except Exception as exc:
        _log_token_failure(provider, exc)
        raise OAuthError("provider_error", flow["purpose"])
    id_token = tokens.get("id_token")
    if not id_token:
        raise OAuthError("provider_error", flow["purpose"])
    try:
        claims = verify_id_token(provider, id_token, flow["nonce"])
    except OAuthError as e:
        raise OAuthError(e.code, flow["purpose"])

    subject = str(claims["sub"])
    identity = database.find_identity(provider, subject)

    if flow["purpose"] == "delete":
        # Re-authentication for account deletion: it must be the very Google
        # identity already linked to the account being deleted.
        if not identity or identity["user_id"] != flow["user_id"]:
            raise OAuthError("reauth_mismatch", "delete")
        if not _reauth_is_fresh(claims):
            raise OAuthError("reauth_stale", "delete")
        return "reauth", database.create_oauth_ticket(
            "delete", user_id=flow["user_id"], provider=provider, subject=subject)

    email = (claims.get("email") or "").strip().lower()
    verified = bool(email) and _truthy(claims.get("email_verified"))
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
