"""
tests/test_oauth.py -- Stage 28/29: login collision fix and Google sign-in.

Google is replaced by tests/mock_idp.py, a real local HTTP identity provider, so
the code under test makes genuine HTTP requests, verifies genuine RS256
signatures and is held to PKCE by the provider. Each "browser" is its own
TestClient with its own cookie jar. All credentials are placeholders; the
database is the throwaway one conftest provides. This proves the protocol
handling; it is NOT a test against real Google.
"""

import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import database
import main
import oauth
from tests.mock_idp import CLIENT_ID, CLIENT_SECRET, MockIdP

API = "https://api.example.test"
FRONT = "https://app.example.test"
PW = "Moonlit9pond"


@pytest.fixture
def idp():
    p = MockIdP()
    yield p
    p.close()


@pytest.fixture(autouse=True)
def configured(monkeypatch, fresh_db, idp):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("PUBLIC_API_BASE", API)
    monkeypatch.setenv("FRONTEND_URL", FRONT)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")      # local mock provider only
    monkeypatch.setitem(oauth.PROVIDERS, "google", idp.provider_config())


def browser():
    """A separate browser: its own cookie jar."""
    return TestClient(main.app, base_url=API, follow_redirects=False)


def signup(c, name, email, pw=PW):
    r = c.post("/signup", json={"username": name, "email": email, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def start(c, path="/auth/google/start"):
    r = c.get(path)
    assert r.status_code == 303, r.text
    return r.headers["location"]


def at_provider(location):
    """Visit the provider's authorize URL (real HTTP); returns the callback URL it redirects to."""
    r = httpx.get(location, follow_redirects=False, timeout=5)
    assert r.status_code == 302
    return r.headers["location"]


def callback(c, cb_url):
    u = urlparse(cb_url)
    return c.get(u.path + ("?" + u.query if u.query else ""))


def frag(resp):
    return parse_qs(urlparse(resp.headers["location"]).fragment)


def full_login(c, idp, **user):
    idp.user.update(user)
    return callback(c, at_provider(start(c)))


def sign_in_google_only(c, idp, **user):
    r = full_login(c, idp, **user)
    t = frag(r)["oauth_code"][0]
    out = c.post("/auth/exchange", json={"ticket": t})
    assert out.status_code == 200, out.text
    return out.json()


def cookie_names(c):
    return [ck.name for ck in c.cookies.jar if ck.name.startswith("loom_oauth_")]


# ===================== login: existing behaviour and collision fix ============

def test_existing_email_and_username_login_still_work():
    c = browser(); signup(c, "ada", "ada@example.test")
    assert c.post("/login", json={"username": "ada", "password": PW}).status_code == 200
    assert c.post("/login", json={"username": "ADA@example.test", "password": PW}).status_code == 200


def test_wrong_password_and_unknown_user_rejected():
    c = browser(); signup(c, "ada", "ada@example.test")
    assert c.post("/login", json={"username": "ada", "password": "Wrong1234x"}).status_code == 401
    assert c.post("/login", json={"username": "nobody", "password": PW}).status_code == 401


def test_new_username_with_at_sign_is_refused():
    r = browser().post("/signup", json={"username": "a@b.test", "email": "x@example.test", "password": PW})
    assert r.status_code == 400


def test_legacy_username_shaped_like_an_email_does_not_hijack_login():
    c = browser(); signup(c, "victim", "victim@example.test", "Victim1pass")
    database.create_user("victim@example.test", "other@example.test", "Other1pass")
    a = c.post("/login", json={"username": "victim@example.test", "password": "Victim1pass"})
    b = c.post("/login", json={"username": "victim@example.test", "password": "Other1pass"})
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["username"] == "victim" and b.json()["username"] == "victim@example.test"


def test_logout_invalidates_token():
    c = browser(); u = signup(c, "ada", "ada@example.test")
    assert c.get("/account", headers=auth(u["token"])).status_code == 200
    assert c.post("/logout", headers=auth(u["token"])).status_code == 200
    assert c.get("/account", headers=auth(u["token"])).status_code == 401


def test_new_login_rotates_the_session_token_no_fixation():
    c = browser(); u = signup(c, "ada", "ada@example.test")
    second = c.post("/login", json={"username": "ada", "password": PW}).json()
    assert second["token"] != u["token"]
    assert c.get("/account", headers=auth(u["token"])).status_code == 401


def test_session_expires_after_thirty_days():
    c = browser(); u = signup(c, "ada", "ada@example.test")
    database._execute("UPDATE users SET token_created_at = '2020-01-01T00:00:00' WHERE username = 'ada'")
    assert c.get("/account", headers=auth(u["token"])).status_code == 401


def test_forgot_password_never_reveals_whether_an_account_exists():
    c = browser(); signup(c, "ada", "ada@example.test")
    a = c.post("/forgot-password", json={"email": "ada@example.test"})
    b = c.post("/forgot-password", json={"email": "nobody@example.test"})
    assert a.json() == b.json() == {"ok": True}


def test_password_reset_still_works_end_to_end():
    c = browser(); signup(c, "ada", "ada@example.test")
    tok = database.create_password_reset_token("ada@example.test")["reset_token"]
    r = c.post("/reset-password", json={"token": tok, "new_password": "BrandNew77pass"})
    assert r.status_code == 200
    assert c.post("/login", json={"username": "ada", "password": "BrandNew77pass"}).status_code == 200
    assert c.post("/login", json={"username": "ada", "password": PW}).status_code == 401


# ===================== configuration safety ================================

def test_providers_endpoint_reports_only_configured(monkeypatch):
    c = browser()
    assert c.get("/auth/providers").json() == {"google": True, "apple": False}
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    assert c.get("/auth/providers").json() == {"google": False, "apple": False}
    assert c.get("/auth/google/start").status_code == 404
    assert c.get("/auth/nope/start").status_code == 404


@pytest.mark.parametrize("var,value", [
    ("PUBLIC_API_BASE", "http://api.example.test"),      # not https
    ("FRONTEND_URL", "http://app.example.test"),         # not https
    ("FRONTEND_URL", ""),                                # unset: would redirect to the backend itself
    ("PUBLIC_API_BASE", "https://api.example.test/x?y=1"),
])
def test_unsafe_or_incomplete_urls_keep_google_off(monkeypatch, var, value):
    monkeypatch.setenv(var, value)
    assert oauth.is_configured("google") is False
    assert browser().get("/auth/google/start").status_code == 404


def test_http_is_allowed_only_for_localhost(monkeypatch):
    monkeypatch.setenv("PUBLIC_API_BASE", "http://127.0.0.1:8000")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:5500")
    assert oauth.is_configured("google") is True
    assert oauth.secure_cookies() is False


def test_config_problems_name_variables_but_never_contain_secret_values(monkeypatch):
    monkeypatch.setenv("PUBLIC_API_BASE", "http://api.example.test")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "super-secret-value-123")
    text = " ".join(oauth.config_problems("google"))
    assert "PUBLIC_API_BASE" in text and "super-secret-value-123" not in text and "test-google-id" not in text


# ===================== valid flow, binding cookie, redirect safety ==========

def test_start_builds_a_pkce_authorization_url_and_binding_cookie(idp):
    c = browser()
    r = c.get("/auth/google/start")
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert r.headers["location"].startswith(idp.base + "/authorize?")
    assert q["client_id"] == [CLIENT_ID] and q["redirect_uri"] == [API + "/auth/google/callback"]
    assert q["code_challenge_method"] == ["S256"] and q["response_type"] == ["code"]
    assert "openid" in q["scope"][0] and "client_secret" not in q
    assert len(q["state"][0]) >= 40 and len(q["nonce"][0]) >= 40
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "secure" in sc and "samesite=lax" in sc
    assert "path=/auth" in sc and "max-age=600" in sc
    assert r.headers["cache-control"] == "no-store"


def test_valid_google_login_creates_account_and_exchanges_once(idp):
    c = browser()
    r = full_login(c, idp)
    assert r.headers["location"].startswith(FRONT + "/#oauth_code=")
    t = frag(r)["oauth_code"][0]
    ok = c.post("/auth/exchange", json={"ticket": t})
    assert ok.status_code == 200 and ok.json()["token"]
    assert c.get("/account", headers=auth(ok.json()["token"])).status_code == 200
    assert c.post("/auth/exchange", json={"ticket": t}).status_code == 400   # single use
    assert cookie_names(c) == []                                              # binding cookie cleared


def test_callback_ignores_any_redirect_parameter(idp):
    c = browser()
    cb = at_provider(start(c)) + "&redirect=https://evil.example&next=https://evil.example&return_to=//evil"
    r = callback(c, cb)
    assert r.headers["location"].startswith(FRONT + "/#")
    assert "evil" not in r.headers["location"]
    assert r.headers["referrer-policy"] == "no-referrer"


def test_pkce_is_enforced_by_the_provider(idp):
    c = browser()
    loc = start(c)
    state = parse_qs(urlparse(loc).query)["state"][0]
    database._execute("UPDATE oauth_flows SET code_verifier = 'a-different-verifier' WHERE state = ?", (state,))
    r = callback(c, at_provider(loc))
    assert frag(r) == {"oauth_error": ["provider_error"]}
    assert idp.token_requests and "code_verifier" in idp.token_requests[0]


def test_user_cancelling_at_the_provider_is_handled(idp):
    c = browser(); idp.mode = "cancel"
    r = callback(c, at_provider(start(c)))
    assert frag(r) == {"oauth_error": ["cancelled"]}
    assert database._execute("SELECT COUNT(*) AS n FROM oauth_flows")[0][0]["n"] == 0


def test_cancel_from_another_browser_is_not_honoured(idp):
    a, b = browser(), browser(); idp.mode = "cancel"
    cb = at_provider(start(a))
    assert frag(callback(b, cb)) == {"oauth_error": ["invalid_request"]}


# ===================== login CSRF and callback rejection ====================

def test_attackers_callback_cannot_log_a_victim_in(idp):
    """The login-CSRF attack: the attacker starts a sign-in with their own Google
    account, then gets the victim's browser to open the resulting callback URL."""
    attacker, victim = browser(), browser()
    idp.user.update(sub="attacker-sub", email="attacker@example.test")
    cb_url = at_provider(start(attacker))          # attacker holds code + state
    # victim has their own unrelated in-flight sign-in cookie
    start(victim)
    r = callback(victim, cb_url)
    assert frag(r) == {"oauth_error": ["invalid_request"]}
    assert database.find_identity("google", "attacker-sub") is None   # nothing was even created
    # and the flow was burned: the attacker cannot retry it either
    assert frag(callback(attacker, cb_url)) == {"oauth_error": ["invalid_request"]}


def test_victim_without_any_cookie_is_rejected(idp):
    attacker, victim = browser(), browser()
    cb_url = at_provider(start(attacker))
    assert frag(callback(victim, cb_url)) == {"oauth_error": ["invalid_request"]}


def test_missing_binding_cookie_is_rejected(idp):
    c = browser()
    cb_url = at_provider(start(c))
    c.cookies.clear()
    assert frag(callback(c, cb_url)) == {"oauth_error": ["invalid_request"]}


def test_modified_binding_cookie_is_rejected(idp):
    c = browser()
    cb_url = at_provider(start(c))
    for ck in c.cookies.jar:
        ck.value = ck.value[:-1] + ("A" if ck.value[-1] != "A" else "B")
    assert frag(callback(c, cb_url)) == {"oauth_error": ["invalid_request"]}


def test_missing_state_is_rejected(idp):
    c = browser(); start(c)
    assert frag(c.get("/auth/google/callback?code=abc")) == {"oauth_error": ["invalid_request"]}


def test_incorrect_or_altered_state_is_rejected(idp):
    c = browser()
    cb_url = at_provider(start(c))
    u = urlparse(cb_url); q = parse_qs(u.query)
    assert frag(c.get("/auth/google/callback", params={"code": q["code"][0], "state": "not-a-state"})) == {"oauth_error": ["invalid_request"]}
    assert frag(c.get("/auth/google/callback", params={"code": q["code"][0], "state": q["state"][0] + "x"})) == {"oauth_error": ["invalid_request"]}


def test_expired_state_is_rejected(idp):
    c = browser()
    cb_url = at_provider(start(c))
    database._execute("UPDATE oauth_flows SET created_at = '2020-01-01T00:00:00'")
    assert frag(callback(c, cb_url)) == {"oauth_error": ["invalid_request"]}


def test_replayed_callback_is_rejected(idp):
    c = browser()
    cb_url = at_provider(start(c))
    first = callback(c, cb_url)
    assert "oauth_code" in frag(first)
    for ck in list(c.cookies.jar):   # even an attacker who kept the cookie cannot replay
        pass
    assert frag(callback(c, cb_url)) == {"oauth_error": ["invalid_request"]}
    assert database._execute("SELECT COUNT(*) AS n FROM users")[0][0]["n"] == 1


def test_concurrent_callbacks_for_one_state_succeed_only_once(idp):
    c = browser()
    cb_url = at_provider(start(c))
    u = urlparse(cb_url)
    cookies = {ck.name: ck.value for ck in c.cookies.jar}
    results, barrier = [], threading.Barrier(2)

    def hit():
        cl = TestClient(main.app, base_url=API, follow_redirects=False, cookies=cookies)
        barrier.wait()
        results.append(frag(cl.get(u.path + "?" + u.query)))
    ts = [threading.Thread(target=hit) for _ in range(2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sum("oauth_code" in r for r in results) == 1
    assert database._execute("SELECT COUNT(*) AS n FROM users")[0][0]["n"] == 1


def test_wrong_provider_in_the_callback_path_is_rejected(idp):
    c = browser()
    cb_url = at_provider(start(c))
    u = urlparse(cb_url)
    assert c.get("/auth/apple/callback?" + u.query).status_code == 404   # apple not configured


# ===================== OIDC token validation ===============================

@pytest.mark.parametrize("name,setup", [
    ("incorrect issuer", lambda i: i.claim_overrides.update(iss="https://evil.example.test")),
    ("incorrect audience", lambda i: i.claim_overrides.update(aud="someone-else")),
    ("expired id_token", lambda i: setattr(i, "exp_offset", -120)),
    ("incorrect nonce", lambda i: setattr(i, "nonce_override", "attacker-nonce")),
    ("missing subject", lambda i: i.claim_overrides.update(sub=None)),
])
def test_invalid_id_tokens_are_rejected(idp, name, setup):
    c = browser(); setup(idp)
    r = callback(c, at_provider(start(c)))
    assert frag(r) == {"oauth_error": ["provider_error"]}, name
    assert database._execute("SELECT COUNT(*) AS n FROM auth_identities")[0][0]["n"] == 0
    assert database._execute("SELECT COUNT(*) AS n FROM users")[0][0]["n"] == 0


def test_forged_id_token_signature_is_rejected(idp):
    c = browser()
    idp.sign_with = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert frag(callback(c, at_provider(start(c)))) == {"oauth_error": ["provider_error"]}


def test_unknown_signing_key_is_rejected(idp):
    c = browser()
    idp.jwks = {"keys": []}
    assert frag(callback(c, at_provider(start(c)))) == {"oauth_error": ["provider_error"]}


def test_provider_error_detail_is_not_leaked(monkeypatch, idp):
    c = browser()
    def boom(*a):
        raise RuntimeError("secret detail from provider")
    monkeypatch.setattr(oauth, "_post_token", boom)
    r = callback(c, at_provider(start(c)))
    assert frag(r) == {"oauth_error": ["provider_error"]} and "secret" not in r.headers["location"]


# ===================== identity and linking safety ==========================

def test_repeated_login_does_not_create_duplicate_accounts(idp):
    c = browser()
    u1 = sign_in_google_only(c, idp)
    u2 = sign_in_google_only(c, idp)
    assert u1["id"] == u2["id"]
    assert database._execute("SELECT COUNT(*) AS n FROM users")[0][0]["n"] == 1


def test_changed_email_at_google_keeps_the_same_account(idp):
    c = browser()
    u1 = sign_in_google_only(c, idp)
    u2 = sign_in_google_only(c, idp, email="renamed@example.test")
    assert u1["id"] == u2["id"]


def test_existing_email_without_linked_identity_does_not_auto_merge(idp):
    c = browser(); existing = signup(c, "ada", "dreamer@example.test")
    r = full_login(c, idp)
    f = frag(r)
    assert "oauth_link" in f and "oauth_code" not in f
    assert database.find_identity("google", "google-sub-1") is None
    assert c.post("/auth/exchange", json={"ticket": f["oauth_link"][0]}).status_code == 400
    # the existing account is untouched and still has only its own password
    assert c.post("/login", json={"username": "ada", "password": PW}).json()["id"] == existing["id"]


def test_link_requires_the_existing_accounts_password(idp):
    c = browser(); existing = signup(c, "ada", "dreamer@example.test")
    t = frag(full_login(c, idp))["oauth_link"][0]
    assert c.post("/auth/link", json={"ticket": t, "password": "Wrong1234x"}).status_code == 401
    assert database.find_identity("google", "google-sub-1") is None
    good = c.post("/auth/link", json={"ticket": t, "password": PW})
    assert good.status_code == 200 and good.json()["id"] == existing["id"]
    assert database.find_identity("google", "google-sub-1")["user_id"] == existing["id"]
    assert c.post("/auth/link", json={"ticket": t, "password": PW}).status_code == 400   # consumed


def test_link_ticket_burns_after_repeated_wrong_passwords(idp):
    c = browser(); signup(c, "ada", "dreamer@example.test")
    t = frag(full_login(c, idp))["oauth_link"][0]
    for _ in range(database.OAUTH_LINK_MAX_ATTEMPTS):
        c.post("/auth/link", json={"ticket": t, "password": "Wrong1234x"})
    assert c.post("/auth/link", json={"ticket": t, "password": PW}).status_code == 400


def test_unverified_google_email_matching_an_account_is_refused(idp):
    c = browser(); signup(c, "ada", "dreamer@example.test")
    r = full_login(c, idp, email_verified=False)
    assert frag(r) == {"oauth_error": ["email_unverified"]}
    assert database.find_identity("google", "google-sub-1") is None


def test_unverified_email_is_not_stored_on_a_new_account(idp):
    c = browser()
    u = sign_in_google_only(c, idp, email="x@example.test", email_verified=False)
    assert database.get_user_by_id(u["id"])["email"] == ""


def test_one_google_identity_cannot_be_linked_to_two_accounts(idp):
    c = browser()
    a = signup(c, "ada", "ada@example.test"); b = signup(c, "bob", "bob@example.test")
    assert database.link_identity_safely(a["id"], "google", "shared-sub", "ada@example.test") == "linked"
    assert database.link_identity_safely(b["id"], "google", "shared-sub", "bob@example.test") == "conflict"
    assert database.link_identity_safely(a["id"], "google", "shared-sub", "ada@example.test") == "already"
    assert database.find_identity("google", "shared-sub")["user_id"] == a["id"]


def test_an_account_cannot_hold_two_google_identities(idp):
    c = browser(); a = signup(c, "ada", "ada@example.test")
    assert database.link_identity_safely(a["id"], "google", "sub-1") == "linked"
    assert database.link_identity_safely(a["id"], "google", "sub-2") == "conflict"


def test_link_ticket_for_an_identity_already_taken_is_a_conflict(idp):
    c = browser()
    a = signup(c, "ada", "dreamer@example.test")
    b = signup(c, "bob", "bob@example.test")
    t = frag(full_login(c, idp))["oauth_link"][0]                # ticket to link google-sub-1 to ada
    database.link_identity(b["id"], "google", "google-sub-1")    # meanwhile bob got it
    r = c.post("/auth/link", json={"ticket": t, "password": PW})
    assert r.status_code == 409
    assert database.find_identity("google", "google-sub-1")["user_id"] == b["id"]
    assert a["id"] != b["id"]


def test_concurrent_link_attempts_with_one_ticket_link_exactly_once(idp):
    c = browser(); a = signup(c, "ada", "dreamer@example.test")
    t = frag(full_login(c, idp))["oauth_link"][0]
    codes, barrier = [], threading.Barrier(2)

    def go():
        cl = TestClient(main.app, base_url=API, follow_redirects=False)
        barrier.wait()
        codes.append(cl.post("/auth/link", json={"ticket": t, "password": PW}).status_code)
    ts = [threading.Thread(target=go) for _ in range(2)]
    [x.start() for x in ts]; [x.join() for x in ts]
    assert sorted(codes) == [200, 400]
    n = database._execute("SELECT COUNT(*) AS n FROM auth_identities WHERE user_id = ?", (a["id"],))[0][0]["n"]
    assert n == 1


def test_concurrent_first_sign_ins_for_one_identity_leave_one_account(idp):
    ids, barrier = [], threading.Barrier(2)

    def go():
        barrier.wait()
        ids.append(database.create_user_from_identity("google", "race-sub", "r@example.test", "r@example.test"))
    ts = [threading.Thread(target=go) for _ in range(2)]
    [x.start() for x in ts]; [x.join() for x in ts]
    assert ids[0] == ids[1]
    assert database._execute("SELECT COUNT(*) AS n FROM users")[0][0]["n"] == 1


# ===================== account deletion =====================================

def reauth_callback(c, token, idp, **user):
    r = c.post("/account/reauth/google", headers=auth(token))
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert url.startswith(API + "/auth/google/start?intent=")
    path = url[len(API):]
    loc = start(c, path)
    q = parse_qs(urlparse(loc).query)
    assert q["prompt"] == ["login"] and q["max_age"] == ["0"]
    idp.user.update(user)
    return callback(c, at_provider(loc))


def test_google_only_account_can_be_deleted_after_reverification(idp):
    c = browser(); u = sign_in_google_only(c, idp)
    assert c.get("/account", headers=auth(u["token"])).json() | {} == {
        "username": u["username"], "email": "dreamer@example.test", "email_verified": True,
        "has_password": False, "google_linked": True}
    # Without verification: refused, even with an empty or guessed password.
    for body in ({}, {"password": ""}, {"password": "anything1A"}):
        assert c.request("DELETE", "/account", json=body, headers=auth(u["token"])).status_code == 401
    r = reauth_callback(c, u["token"], idp)
    ticket = frag(r)["oauth_reauth"][0]
    assert c.request("DELETE", "/account", json={"reauth_ticket": ticket}, headers=auth(u["token"])).json() == {"deleted": True}
    assert c.get("/account", headers=auth(u["token"])).status_code == 401           # session gone
    assert database.get_user_by_id(u["id"]) is None
    assert database.find_identity("google", "google-sub-1") is None                  # identity gone too
    assert database._execute("SELECT COUNT(*) AS n FROM oauth_tickets WHERE user_id = ?", (u["id"],))[0][0]["n"] == 0


def test_deleting_removes_dreams_and_the_same_google_account_starts_fresh(idp):
    c = browser(); u = sign_in_google_only(c, idp)
    database._execute("INSERT INTO dreams (user_id, timestamp, raw_text) VALUES (?, '2026-01-01', 'x')", (u["id"],))
    ticket = frag(reauth_callback(c, u["token"], idp))["oauth_reauth"][0]
    c.request("DELETE", "/account", json={"reauth_ticket": ticket}, headers=auth(u["token"]))
    assert database._execute("SELECT COUNT(*) AS n FROM dreams WHERE user_id = ?", (u["id"],))[0][0]["n"] == 0
    again = sign_in_google_only(c, idp)                                              # no orphan, no crash
    assert again["id"] != u["id"]


def test_deletion_with_a_different_google_identity_is_rejected(idp):
    c = browser(); u = sign_in_google_only(c, idp)
    r = reauth_callback(c, u["token"], idp, sub="some-other-google-sub", email="dreamer@example.test")
    assert frag(r) == {"oauth_error": ["reauth_mismatch"], "purpose": ["delete"]}
    assert database.get_user_by_id(u["id"]) is not None
    assert database._execute("SELECT COUNT(*) AS n FROM oauth_tickets WHERE kind = 'delete'")[0][0]["n"] == 0


def test_deletion_ticket_cannot_be_used_by_another_signed_in_user(idp):
    c = browser(); u = sign_in_google_only(c, idp)
    other = signup(c, "mallory", "m@example.test")
    ticket = frag(reauth_callback(c, u["token"], idp))["oauth_reauth"][0]
    r = c.request("DELETE", "/account", json={"reauth_ticket": ticket}, headers=auth(other["token"]))
    assert r.status_code == 401
    assert database.get_user_by_id(u["id"]) is not None and database.get_user_by_id(other["id"]) is not None


def test_deletion_reverification_expires(idp):
    c = browser(); u = sign_in_google_only(c, idp)
    ticket = frag(reauth_callback(c, u["token"], idp))["oauth_reauth"][0]
    database._execute("UPDATE oauth_tickets SET created_at = '2020-01-01T00:00:00'")
    assert c.request("DELETE", "/account", json={"reauth_ticket": ticket}, headers=auth(u["token"])).status_code == 401
    assert database.get_user_by_id(u["id"]) is not None


def test_deletion_ticket_cannot_be_replayed_or_used_concurrently(idp):
    c = browser(); u = sign_in_google_only(c, idp)
    ticket = frag(reauth_callback(c, u["token"], idp))["oauth_reauth"][0]
    codes, barrier = [], threading.Barrier(2)

    def go():
        cl = TestClient(main.app, base_url=API, follow_redirects=False)
        barrier.wait()
        codes.append(cl.request("DELETE", "/account", json={"reauth_ticket": ticket}, headers=auth(u["token"])).status_code)
    ts = [threading.Thread(target=go) for _ in range(2)]
    [x.start() for x in ts]; [x.join() for x in ts]
    assert sorted(codes)[0] == 200 or 200 in codes
    assert codes.count(200) == 1
    assert c.request("DELETE", "/account", json={"reauth_ticket": ticket}, headers=auth(u["token"])).status_code == 401


def test_cancelling_the_deletion_check_deletes_nothing(idp):
    c = browser(); u = sign_in_google_only(c, idp)
    r = c.post("/account/reauth/google", headers=auth(u["token"]))
    loc = start(c, r.json()["url"][len(API):])
    idp.mode = "cancel"
    cb = callback(c, at_provider(loc))
    assert frag(cb) == {"oauth_error": ["cancelled"], "purpose": ["delete"]}
    assert database.get_user_by_id(u["id"]) is not None
    assert c.get("/account", headers=auth(u["token"])).status_code == 200


def test_reauth_intent_is_single_use_and_needs_a_session(idp):
    c = browser(); u = sign_in_google_only(c, idp)
    assert c.post("/account/reauth/google").status_code == 401
    url = c.post("/account/reauth/google", headers=auth(u["token"])).json()["url"]
    assert c.get(url[len(API):]).status_code == 303
    assert c.get(url[len(API):]).status_code == 400                                  # intent consumed


def test_deletion_callback_from_another_browser_is_rejected(idp):
    c = browser(); u = sign_in_google_only(c, idp)
    other_browser = browser()
    url = c.post("/account/reauth/google", headers=auth(u["token"])).json()["url"]
    loc = start(c, url[len(API):])
    cb_url = at_provider(loc)
    assert frag(callback(other_browser, cb_url)) == {"oauth_error": ["invalid_request"]}
    assert database._execute("SELECT COUNT(*) AS n FROM oauth_tickets WHERE kind = 'delete'")[0][0]["n"] == 0


def test_reauth_requires_a_linked_google_identity(idp):
    c = browser(); u = signup(c, "ada", "ada@example.test")
    assert c.post("/account/reauth/google", headers=auth(u["token"])).status_code == 400


def test_password_account_deletion_is_unchanged_and_both_methods_work(idp):
    c = browser(); u = signup(c, "ada", "ada@example.test")
    assert c.request("DELETE", "/account", json={"password": "Wrong1234x"}, headers=auth(u["token"])).status_code == 401
    assert c.request("DELETE", "/account", json={}, headers=auth(u["token"])).status_code == 401
    assert c.request("DELETE", "/account", json={"password": PW}, headers=auth(u["token"])).json() == {"deleted": True}
    # an account with both a password and Google can verify either way
    v = signup(c, "bea", "dreamer@example.test")
    t = frag(full_login(c, idp))["oauth_link"][0]
    linked = c.post("/auth/link", json={"ticket": t, "password": PW}).json()
    ticket = frag(reauth_callback(c, linked["token"], idp))["oauth_reauth"][0]
    assert c.request("DELETE", "/account", json={"reauth_ticket": ticket}, headers=auth(linked["token"])).json() == {"deleted": True}
    assert v["id"] == linked["id"]


# ===================== isolation and logging ================================

def test_tests_never_touch_a_production_database():
    assert database.USE_TURSO is False
    assert "loom_test_" in database.DB_PATH and database.DB_PATH.endswith(".db")
    import os
    assert not os.environ.get("TURSO_DATABASE_URL")


def test_no_sensitive_values_reach_the_application_logs(idp, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    c = browser()
    loc = start(c)
    q = parse_qs(urlparse(loc).query)
    logging.disable(logging.CRITICAL)        # the test's own HTTP call to the mock provider is not application logging
    try:
        cb = at_provider(loc)
    finally:
        logging.disable(logging.NOTSET)
    code = parse_qs(urlparse(cb).query)["code"][0]
    r = callback(c, cb)
    ticket = frag(r)["oauth_code"][0]
    tok = c.post("/auth/exchange", json={"ticket": ticket}).json()["token"]
    # "httpx2" is the TestClient logging its own simulated browser request line,
    # not the application; everything the app itself logs is included.
    out = capsys.readouterr().out + "\n".join(
        r.getMessage() for r in caplog.records if r.name != "httpx2")
    id_token = None
    for needle in (code, q["state"][0], q["nonce"][0], ticket, tok, CLIENT_SECRET,
                   idp.token_requests[0]["code_verifier"]):
        assert needle not in out, "sensitive value found in logs"


def test_uvicorn_access_log_query_strings_are_redacted_for_auth_paths():
    f = main._RedactAuthQuery()
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4:5", "GET", "/auth/google/callback?code=SECRETCODE&state=SECRETSTATE", "1.1", 303), None)
    f.filter(rec)
    assert "SECRET" not in rec.getMessage() and "/auth/google/callback?[redacted]" in rec.getMessage()
    other = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                              ("1.2.3.4:5", "GET", "/dreams?limit=5", "1.1", 200), None)
    f.filter(other)
    assert "limit=5" in other.getMessage()


# ===================== Stage 30: cookie scoping and lifecycle =====================

def test_binding_cookie_has_no_domain_attribute_and_is_per_flow():
    """Host-only (no Domain=) so it is never shared with sibling hosts; one cookie
    name per flow so two tabs cannot overwrite each other."""
    c = browser()
    r1, r2 = c.get("/auth/google/start"), c.get("/auth/google/start")
    for r in (r1, r2):
        assert "domain=" not in r.headers["set-cookie"].lower()
    n1 = r1.headers["set-cookie"].split("=")[0]
    n2 = r2.headers["set-cookie"].split("=")[0]
    assert n1.startswith("loom_oauth_") and n1 != n2


def test_binding_cookie_is_cleared_by_the_callback(idp):
    c = browser()
    r = full_login(c, idp)
    cleared = [h for h in r.headers.get_list("set-cookie") if h.startswith("loom_oauth_")]
    assert cleared and "max-age=0" in cleared[0].lower()


def test_secure_flag_follows_https_and_is_never_dropped_on_https(monkeypatch):
    c = browser()
    assert "secure" in c.get("/auth/google/start").headers["set-cookie"].lower()      # https API
    monkeypatch.setenv("PUBLIC_API_BASE", "http://localhost:8000")                     # local development only
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    r = TestClient(main.app, base_url="http://localhost:8000", follow_redirects=False).get("/auth/google/start")
    assert r.status_code == 303 and "secure" not in r.headers["set-cookie"].lower()


def test_cookie_older_than_its_flow_is_useless(idp, monkeypatch):
    """Flow lifetime (10 min) bounds the cookie even if a client kept it."""
    from datetime import timedelta
    c = browser()
    cb = at_provider(start(c))
    monkeypatch.setattr(database, "OAUTH_FLOW_LIFETIME", timedelta(seconds=-1))
    assert frag(callback(c, cb)).get("oauth_error")


# ===================== Stage 30 Phase B: findings from the first real-Google test ==========

def test_deletion_proof_requires_a_recent_google_sign_in_when_google_reports_auth_time(idp):
    c = browser(); u = sign_in_google_only(c, idp)
    idp.auth_age = 3600                               # Google says the person last signed in an hour ago
    r = reauth_callback(c, u["token"], idp)
    f = frag(r)
    assert f.get("oauth_error") == ["reauth_stale"] and "oauth_reauth" not in f
    assert database.get_user_by_id(u["id"]) is not None and not c.request(
        "DELETE", "/account", json={"reauth_ticket": "whatever"}, headers=auth(u["token"])).is_success


def test_fresh_auth_time_is_accepted_and_its_presence_is_logged(idp, caplog):
    c = browser(); u = sign_in_google_only(c, idp)
    with caplog.at_level(logging.INFO, logger="loom"):
        idp.auth_age = 5
        assert "oauth_reauth" in frag(reauth_callback(c, u["token"], idp))
    log = " ".join(r.getMessage() for r in caplog.records)
    assert '"auth_time_present": true' in log


def test_missing_auth_time_is_refused_not_treated_as_fresh(idp, caplog):
    c = browser(); u = sign_in_google_only(c, idp)
    idp.auth_age = None                               # provider omits the claim: freshness is unproven
    with caplog.at_level(logging.INFO, logger="loom"):
        f = frag(reauth_callback(c, u["token"], idp))
    assert f.get("oauth_error") == ["reauth_unverified"] and "oauth_reauth" not in f
    assert '"auth_time_present": false' in " ".join(r.getMessage() for r in caplog.records)
    assert database.get_user_by_id(u["id"]) is not None


def test_auth_time_before_this_flow_started_or_in_the_future_is_refused(idp):
    c = browser(); u = sign_in_google_only(c, idp)
    idp.auth_age = 200                                # recent (<5 min) but before the flow began just now
    assert frag(reauth_callback(c, u["token"], idp)).get("oauth_error") == ["reauth_stale"]
    idp.auth_age = -3600                              # claims to be from an hour in the future
    assert frag(reauth_callback(c, u["token"], idp)).get("oauth_error") == ["reauth_stale"]
    assert database.get_user_by_id(u["id"]) is not None


def test_token_exchange_failure_logs_only_status_and_error_code(idp, monkeypatch, caplog):
    secret_text = "client-secret-ABC-should-never-appear"

    def boom(provider, code, verifier):
        req = httpx.Request("POST", "https://oauth2.example.invalid/token")
        resp = httpx.Response(401, request=req, json={"error": "invalid_client",
                                                       "error_description": secret_text})
        raise httpx.HTTPStatusError("401", request=req, response=resp)
    monkeypatch.setattr(oauth, "_post_token", boom)
    c = browser()
    with caplog.at_level(logging.INFO, logger="loom"):
        r = callback(c, at_provider(start(c)))
    assert frag(r).get("oauth_error") == ["provider_error"]
    log = " ".join(x.getMessage() for x in caplog.records)
    assert "oauth_token_exchange_failed" in log and "invalid_client" in log and '"http_status": 401' in log
    assert secret_text not in log and "code=" not in log


def test_token_exchange_error_code_that_is_not_a_plain_token_is_not_logged(idp, monkeypatch, caplog):
    def boom(provider, code, verifier):
        req = httpx.Request("POST", "https://x.invalid/token")
        raise httpx.HTTPStatusError("x", request=req, response=httpx.Response(
            400, request=req, json={"error": "Some Long Text With client_secret=abc"}))
    monkeypatch.setattr(oauth, "_post_token", boom)
    c = browser()
    with caplog.at_level(logging.INFO, logger="loom"):
        callback(c, at_provider(start(c)))
    log = " ".join(x.getMessage() for x in caplog.records)
    assert "http_400" in log and "client_secret" not in log


def test_google_account_persists_across_restarts_and_never_duplicates(idp):
    c = browser()
    first = full_login(c, idp)
    uid = database.find_identity("google", "google-sub-1")["user_id"]
    database._execute("INSERT INTO dreams (user_id, timestamp, raw_text) VALUES (?, ?, ?)",
                      (uid, "2026-01-01T00:00:00", "synthetic dream"))
    for _ in range(3):                                # three "server restarts"
        database.init_db()
        r = full_login(browser(), idp)
        assert "oauth_code" in frag(r)
    assert database._execute("SELECT COUNT(*) AS n FROM users")[0][0]["n"] == 1
    assert database._execute("SELECT COUNT(*) AS n FROM auth_identities")[0][0]["n"] == 1
    assert database._execute("SELECT COUNT(*) AS n FROM dreams WHERE user_id = ?", (uid,))[0][0]["n"] == 1
    assert database.find_identity("google", "google-sub-1")["user_id"] == uid


def test_linked_account_keeps_one_identity_and_password_login_after_restart(idp):
    c = browser()
    pwu = signup(c, "linker", "dreamer@example.test")
    r = full_login(browser(), idp)                    # same email: offered linking, not merged
    ticket = frag(r)["oauth_link"][0]
    assert database._execute("SELECT COUNT(*) AS n FROM auth_identities")[0][0]["n"] == 0
    assert c.post("/auth/link", json={"ticket": ticket, "password": PW}).status_code == 200
    database.init_db()
    again = full_login(browser(), idp)
    assert "oauth_code" in frag(again)                # now a plain login
    assert database._execute("SELECT COUNT(*) AS n FROM users")[0][0]["n"] == 1
    assert database._execute("SELECT user_id FROM auth_identities")[0][0]["user_id"] == pwu["id"]
    assert c.post("/login", json={"username": "linker", "password": PW}).status_code == 200
