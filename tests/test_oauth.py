"""
tests/test_oauth.py -- Stage 28: login collision fix, "@" usernames, and
Sign in with Google / Apple. No network: the provider token endpoint and
JWKS are mocked, and id_tokens are signed with a throwaway RSA key made
here. Credentials below are test placeholders only.
"""

import json
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import database
import main
import oauth

client = TestClient(main.app, follow_redirects=False)

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))
JWK.update({"kid": "test-key", "alg": "RS256", "use": "sig"})
PW = "Moonlit9pond"


@pytest.fixture(autouse=True)
def configured(monkeypatch, fresh_db):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-google-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-google-secret")
    monkeypatch.setenv("PUBLIC_API_BASE", "https://api.example.test")
    monkeypatch.setattr(main, "FRONTEND_URL", "https://app.example.test/loom")
    monkeypatch.setattr(oauth, "_fetch_jwks", lambda provider: {"keys": [JWK]})


def _signup(name, email, pw=PW):
    r = client.post("/signup", json={"username": name, "email": email, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()


def _start(provider="google"):
    r = client.get(f"/auth/{provider}/start")
    assert r.status_code == 303
    q = parse_qs(urlparse(r.headers["location"]).query)
    return r, q


def _token(nonce, sub="g-1", email="dreamer@example.test", verified=True,
           iss="https://accounts.google.com", aud="test-google-id", exp=None, kid="test-key"):
    claims = {"iss": iss, "aud": aud, "sub": sub, "nonce": nonce,
              "exp": exp or int(time.time()) + 600, "email": email,
              "email_verified": verified}
    return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": kid})


def _callback(monkeypatch, make_token, **kw):
    _, q = _start()
    monkeypatch.setattr(oauth, "_post_token",
                        lambda p, c, v: {"id_token": make_token(q["nonce"][0])})
    return client.get("/auth/google/callback",
                      params={"state": q["state"][0], "code": "abc"}), q


def _fragment(resp):
    return parse_qs(urlparse(resp.headers["location"]).fragment)


# --- login: existing behaviour and the collision fix ---------------------

def test_existing_email_and_username_login_still_work():
    _signup("ada", "ada@example.test")
    assert client.post("/login", json={"username": "ada", "password": PW}).status_code == 200
    assert client.post("/login", json={"username": "ADA@example.test", "password": PW}).status_code == 200


def test_wrong_password_and_unknown_user_rejected():
    _signup("ada", "ada@example.test")
    assert client.post("/login", json={"username": "ada", "password": "Wrong1234x"}).status_code == 401
    assert client.post("/login", json={"username": "nobody", "password": PW}).status_code == 401


def test_new_username_with_at_sign_is_refused():
    r = client.post("/signup", json={"username": "a@b.test", "email": "x@example.test", "password": PW})
    assert r.status_code == 400


def test_legacy_username_shaped_like_an_email_does_not_hijack_login():
    victim = _signup("victim", "victim@example.test", "Victim1pass")
    # A legacy account whose *username* equals the victim's email.
    database.create_user("victim@example.test", "other@example.test", "Other1pass")
    # Each owner still gets into their own account.
    a = client.post("/login", json={"username": "victim@example.test", "password": "Victim1pass"})
    b = client.post("/login", json={"username": "victim@example.test", "password": "Other1pass"})
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["username"] == "victim"
    assert b.json()["username"] == "victim@example.test"
    assert victim["username"] == "victim"


def test_logout_invalidates_token_and_login_rotates_it():
    u = _signup("ada", "ada@example.test")
    h = {"Authorization": f"Bearer {u['token']}"}
    assert client.get("/account", headers=h).status_code == 200
    assert client.post("/logout", headers=h).status_code == 200
    assert client.get("/account", headers=h).status_code == 401


def test_session_expires_after_thirty_days():
    u = _signup("ada", "ada@example.test")
    old = "2020-01-01T00:00:00"
    database._execute("UPDATE users SET token_created_at = ? WHERE username = 'ada'", (old,))
    r = client.get("/account", headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 401


def test_forgot_password_never_reveals_whether_an_account_exists():
    _signup("ada", "ada@example.test")
    a = client.post("/forgot-password", json={"email": "ada@example.test"})
    b = client.post("/forgot-password", json={"email": "nobody@example.test"})
    assert a.json() == b.json() == {"ok": True}


# --- providers / start ----------------------------------------------------

def test_providers_endpoint_reports_only_configured(monkeypatch):
    assert client.get("/auth/providers").json() == {"google": True, "apple": False}
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    assert client.get("/auth/providers").json() == {"google": False, "apple": False}
    assert client.get("/auth/google/start").status_code == 404
    assert client.get("/auth/nope/start").status_code == 404


def test_start_builds_a_pkce_authorization_url():
    r, q = _start()
    assert r.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert q["client_id"] == ["test-google-id"]
    assert q["redirect_uri"] == ["https://api.example.test/auth/google/callback"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["response_type"] == ["code"] and "openid" in q["scope"][0]
    assert "client_secret" not in q


# --- callback: new account, returning identity, no auto-merge -------------

def test_new_google_user_gets_an_account_and_exchanges_ticket_once(monkeypatch):
    resp, _ = _callback(monkeypatch, lambda n: _token(n))
    frag = _fragment(resp)
    assert resp.headers["location"].startswith("https://app.example.test/loom/#oauth_code=")
    ticket = frag["oauth_code"][0]
    ok = client.post("/auth/exchange", json={"ticket": ticket})
    assert ok.status_code == 200 and ok.json()["token"]
    assert client.get("/account", headers={"Authorization": f"Bearer {ok.json()['token']}"}).status_code == 200
    assert client.post("/auth/exchange", json={"ticket": ticket}).status_code == 400


def test_returning_identity_logs_into_the_same_account(monkeypatch):
    r1, _ = _callback(monkeypatch, lambda n: _token(n))
    u1 = client.post("/auth/exchange", json={"ticket": _fragment(r1)["oauth_code"][0]}).json()
    r2, _ = _callback(monkeypatch, lambda n: _token(n))
    u2 = client.post("/auth/exchange", json={"ticket": _fragment(r2)["oauth_code"][0]}).json()
    assert u1["id"] == u2["id"]


def test_matching_email_does_not_auto_merge(monkeypatch):
    existing = _signup("ada", "dreamer@example.test")
    resp, _ = _callback(monkeypatch, lambda n: _token(n))
    frag = _fragment(resp)
    assert "oauth_link" in frag and "oauth_code" not in frag
    # Nothing linked yet, and the ticket can't be used as a login.
    assert database.find_identity("google", "g-1") is None
    assert client.post("/auth/exchange", json={"ticket": frag["oauth_link"][0]}).status_code == 400
    assert existing["username"] == "ada"


def test_link_requires_the_existing_accounts_password(monkeypatch):
    existing = _signup("ada", "dreamer@example.test")
    resp, _ = _callback(monkeypatch, lambda n: _token(n))
    ticket = _fragment(resp)["oauth_link"][0]
    bad = client.post("/auth/link", json={"ticket": ticket, "password": "Wrong1234x"})
    assert bad.status_code == 401 and database.find_identity("google", "g-1") is None
    good = client.post("/auth/link", json={"ticket": ticket, "password": PW})
    assert good.status_code == 200 and good.json()["id"] == existing["id"]
    assert database.find_identity("google", "g-1")["user_id"] == existing["id"]
    assert client.post("/auth/link", json={"ticket": ticket, "password": PW}).status_code == 400


def test_link_ticket_burns_after_repeated_wrong_passwords(monkeypatch):
    _signup("ada", "dreamer@example.test")
    resp, _ = _callback(monkeypatch, lambda n: _token(n))
    ticket = _fragment(resp)["oauth_link"][0]
    for _ in range(database.OAUTH_LINK_MAX_ATTEMPTS):
        client.post("/auth/link", json={"ticket": ticket, "password": "Wrong1234x"})
    assert client.post("/auth/link", json={"ticket": ticket, "password": PW}).status_code == 400


def test_unverified_provider_email_matching_an_account_is_refused(monkeypatch):
    _signup("ada", "dreamer@example.test")
    resp, _ = _callback(monkeypatch, lambda n: _token(n, verified=False))
    assert _fragment(resp) == {"oauth_error": ["email_unverified"]}
    assert database.find_identity("google", "g-1") is None


def test_unverified_email_is_not_stored_on_a_new_account(monkeypatch):
    resp, _ = _callback(monkeypatch, lambda n: _token(n, email="x@example.test", verified=False))
    uid = client.post("/auth/exchange", json={"ticket": _fragment(resp)["oauth_code"][0]}).json()["id"]
    assert database.get_user_by_id(uid)["email"] == ""


def test_provider_only_account_cannot_password_login(monkeypatch):
    resp, _ = _callback(monkeypatch, lambda n: _token(n))
    uid = client.post("/auth/exchange", json={"ticket": _fragment(resp)["oauth_code"][0]}).json()["id"]
    assert database.user_has_password(uid) is False
    assert client.post("/login", json={"username": "dreamer@example.test", "password": "anything1A"}).status_code == 401


# --- token validation -----------------------------------------------------

@pytest.mark.parametrize("bad", [
    lambda n: _token("wrong-nonce"),
    lambda n: _token(n, aud="someone-else"),
    lambda n: _token(n, iss="https://evil.example.test"),
    lambda n: _token(n, exp=int(time.time()) - 10),
    lambda n: _token(n, kid="unknown-key"),
])
def test_invalid_id_tokens_are_rejected(monkeypatch, bad):
    resp, _ = _callback(monkeypatch, bad)
    assert _fragment(resp) == {"oauth_error": ["provider_error"]}
    assert database._execute("SELECT COUNT(*) AS c FROM auth_identities")[0][0]["c"] == 0


def test_token_signed_with_a_different_key_is_rejected(monkeypatch):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def forged(n):
        return jwt.encode({"iss": "https://accounts.google.com", "aud": "test-google-id", "sub": "x",
                           "nonce": n, "exp": int(time.time()) + 60}, other,
                          algorithm="RS256", headers={"kid": "test-key"})
    resp, _ = _callback(monkeypatch, forged)
    assert _fragment(resp) == {"oauth_error": ["provider_error"]}


def test_state_is_single_use_and_unknown_state_rejected(monkeypatch):
    _, q = _start()
    monkeypatch.setattr(oauth, "_post_token", lambda p, c, v: {"id_token": _token(q["nonce"][0])})
    first = client.get("/auth/google/callback", params={"state": q["state"][0], "code": "abc"})
    again = client.get("/auth/google/callback", params={"state": q["state"][0], "code": "abc"})
    assert "oauth_code" in _fragment(first)
    assert _fragment(again) == {"oauth_error": ["invalid_request"]}
    unknown = client.get("/auth/google/callback", params={"state": "nope", "code": "abc"})
    assert _fragment(unknown) == {"oauth_error": ["invalid_request"]}


def test_expired_state_is_rejected(monkeypatch):
    _, q = _start()
    database._execute("UPDATE oauth_flows SET created_at = '2020-01-01T00:00:00'")
    monkeypatch.setattr(oauth, "_post_token", lambda p, c, v: {"id_token": _token(q["nonce"][0])})
    r = client.get("/auth/google/callback", params={"state": q["state"][0], "code": "abc"})
    assert _fragment(r) == {"oauth_error": ["invalid_request"]}


def test_user_cancelling_at_the_provider_is_handled():
    r = client.get("/auth/google/callback", params={"error": "access_denied"})
    assert _fragment(r) == {"oauth_error": ["cancelled"]}


def test_provider_token_endpoint_failure_is_generic(monkeypatch):
    _, q = _start()

    def boom(*a):
        raise RuntimeError("secret detail")
    monkeypatch.setattr(oauth, "_post_token", boom)
    r = client.get("/auth/google/callback", params={"state": q["state"][0], "code": "abc"})
    assert _fragment(r) == {"oauth_error": ["provider_error"]}
    assert "secret" not in r.headers["location"]


def test_expired_login_ticket_is_rejected(monkeypatch):
    resp, _ = _callback(monkeypatch, lambda n: _token(n))
    ticket = _fragment(resp)["oauth_code"][0]
    database._execute("UPDATE oauth_tickets SET created_at = '2020-01-01T00:00:00'")
    assert client.post("/auth/exchange", json={"ticket": ticket}).status_code == 400


# --- Apple ----------------------------------------------------------------

def test_apple_uses_form_post_and_post_callback(monkeypatch):
    pem = KEY.private_bytes(
        encoding=__import__("cryptography.hazmat.primitives.serialization", fromlist=["x"]).Encoding.PEM,
        format=__import__("cryptography.hazmat.primitives.serialization", fromlist=["x"]).PrivateFormat.PKCS8,
        encryption_algorithm=__import__("cryptography.hazmat.primitives.serialization", fromlist=["x"]).NoEncryption(),
    ).decode()
    for k, v in {"APPLE_CLIENT_ID": "test.apple.id", "APPLE_TEAM_ID": "TEAMTEST01",
                 "APPLE_KEY_ID": "KEYTEST001"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("APPLE_PRIVATE_KEY", pem)
    assert client.get("/auth/providers").json()["apple"] is True
    r, q = _start("apple")
    assert q["response_mode"] == ["form_post"]
    assert r.headers["location"].startswith("https://appleid.apple.com/auth/authorize?")

    def apple_token(p, c, v):
        return {"id_token": _token(q["nonce"][0], sub="a-1", email="abc@privaterelay.appleid.com",
                                   verified="true", iss="https://appleid.apple.com", aud="test.apple.id")}
    monkeypatch.setattr(oauth, "_post_token", apple_token)
    resp = client.post("/auth/apple/callback", data={"state": q["state"][0], "code": "abc"})
    assert "oauth_code" in _fragment(resp)


def test_apple_client_secret_is_a_short_lived_es256_jwt(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization as ser
    ek = ec.generate_private_key(ec.SECP256R1())
    pem = ek.private_bytes(ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption()).decode()
    monkeypatch.setenv("APPLE_CLIENT_ID", "test.apple.id")
    monkeypatch.setenv("APPLE_TEAM_ID", "TEAMTEST01")
    monkeypatch.setenv("APPLE_KEY_ID", "KEYTEST001")
    monkeypatch.setenv("APPLE_PRIVATE_KEY", pem.replace("\n", "\\n"))
    sec = oauth._apple_client_secret()
    claims = jwt.decode(sec, ek.public_key(), algorithms=["ES256"], audience="https://appleid.apple.com")
    assert claims["iss"] == "TEAMTEST01" and claims["sub"] == "test.apple.id"
    assert claims["exp"] - claims["iat"] <= 600
    assert jwt.get_unverified_header(sec)["kid"] == "KEYTEST001"
