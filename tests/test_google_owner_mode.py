"""
Owner-only Google sign-in testing switch (oauth.signin_mode and friends).

Until GOOGLE_SIGNIN_MODE=public, Google must be: invisible to ordinary visitors, unstartable
without a one-time ticket minted for the holder of GOOGLE_TEST_KEY, and refused at the callback
for any account whose verified email is not in GOOGLE_TEST_EMAILS -- before anything is created,
linked or signed in. Uses the same local mock identity provider as tests/test_oauth.py;
placeholder credentials only, no real Google.
"""
import re
from pathlib import Path

import pytest

import database
import oauth
from tests.test_oauth import (  # noqa: F401  (fixtures + helpers shared with the main OAuth tests)
    API, PW, at_provider, auth, browser, callback, configured, frag, idp, signup, start,
)

ROOT = Path(__file__).resolve().parents[1]
KEY = "k" * 32
OWNER = "owner@example.test"


@pytest.fixture
def restricted(monkeypatch):
    monkeypatch.setenv("GOOGLE_SIGNIN_MODE", "test")
    monkeypatch.setenv("GOOGLE_TEST_KEY", KEY)
    monkeypatch.setenv("GOOGLE_TEST_EMAILS", f" {OWNER.upper()} , second@example.test ")


def ticket_url(c, key=KEY):
    r = c.post("/auth/google/test-start", headers={"X-Google-Test-Key": key})
    assert r.status_code == 200, r.text
    return r.json()["url"][len(API):]


def user_count():
    return database._execute("SELECT COUNT(*) AS n FROM users")[0][0]["n"]


# ---------------- visibility ----------------

def test_unset_mode_fails_closed(monkeypatch):
    monkeypatch.delenv("GOOGLE_SIGNIN_MODE")
    monkeypatch.setenv("GOOGLE_TEST_KEY", KEY)
    assert oauth.signin_mode() == "test"
    assert browser().get("/auth/providers").json() == {"google": False, "apple": False}


def test_ordinary_visitors_and_wrong_keys_see_no_google(restricted):
    c = browser()
    assert c.get("/auth/providers").json()["google"] is False
    assert c.get("/auth/providers", headers={"X-Google-Test-Key": "wrong" * 8}).json()["google"] is False
    assert c.get("/auth/providers", headers={"X-Google-Test-Key": ""}).json()["google"] is False


def test_owner_key_reveals_google_and_responses_are_not_cached(restricted):
    r = browser().get("/auth/providers", headers={"X-Google-Test-Key": KEY})
    assert r.json()["google"] is True
    assert r.headers["cache-control"] == "no-store" and "X-Google-Test-Key" in r.headers["vary"]


def test_short_or_missing_server_key_never_opens_anything(restricted, monkeypatch):
    monkeypatch.setenv("GOOGLE_TEST_KEY", "short")
    assert browser().get("/auth/providers", headers={"X-Google-Test-Key": "short"}).json()["google"] is False
    monkeypatch.setenv("GOOGLE_TEST_KEY", "")
    assert browser().get("/auth/providers", headers={"X-Google-Test-Key": ""}).json()["google"] is False


# ---------------- starting a sign-in ----------------

def test_start_needs_a_ticket_and_the_key_buys_one(restricted):
    c = browser()
    assert c.get("/auth/google/start").status_code == 404
    assert c.get("/auth/google/start?test_ticket=nonsense").status_code == 404
    assert c.post("/auth/google/test-start").status_code == 404
    assert c.post("/auth/google/test-start", headers={"X-Google-Test-Key": "x" * 32}).status_code == 404
    url = ticket_url(c)
    assert KEY not in url                                   # the key never travels in a URL
    assert c.get(url).status_code == 303
    assert c.get(url).status_code == 404                    # one-time


def test_test_start_does_not_exist_once_public(restricted, monkeypatch):
    monkeypatch.setenv("GOOGLE_SIGNIN_MODE", "public")
    c = browser()
    assert c.post("/auth/google/test-start", headers={"X-Google-Test-Key": KEY}).status_code == 404
    assert c.get("/auth/providers").json()["google"] is True
    assert c.get("/auth/google/start").status_code == 303


# ---------------- the callback is restricted too ----------------

def test_allowed_account_signs_in_and_case_is_ignored(restricted, idp):
    c = browser(); idp.user.update(sub="owner-sub", email="Owner@Example.Test")
    r = callback(c, at_provider(start(c, ticket_url(c))))
    t = frag(r)["oauth_code"][0]
    assert c.post("/auth/exchange", json={"ticket": t}).status_code == 200


def test_other_google_accounts_are_refused_before_anything_is_written(restricted, idp):
    c = browser(); idp.user.update(sub="stranger-sub", email="stranger@example.test")
    before = user_count()
    r = callback(c, at_provider(start(c, ticket_url(c))))
    assert frag(r) == {"oauth_error": ["not_allowed"]}
    assert user_count() == before
    assert database.find_identity("google", "stranger-sub") is None
    assert database._execute("SELECT COUNT(*) AS n FROM oauth_tickets")[0][0]["n"] == 0


def test_unverified_email_is_refused_even_if_listed(restricted, idp):
    c = browser(); idp.user.update(sub="owner-sub", email=OWNER, email_verified=False)
    assert frag(callback(c, at_provider(start(c, ticket_url(c))))) == {"oauth_error": ["not_allowed"]}


def test_matching_an_existing_email_is_refused_unless_listed(restricted, idp):
    web = browser(); signup(web, "victim", "victim@example.test")
    c = browser(); idp.user.update(sub="x-sub", email="victim@example.test")
    assert frag(callback(c, at_provider(start(c, ticket_url(c))))) == {"oauth_error": ["not_allowed"]}
    assert database._execute("SELECT COUNT(*) AS n FROM oauth_tickets")[0][0]["n"] == 0


def test_account_linking_still_needs_the_password_for_an_allowed_account(restricted, idp):
    web = browser(); signup(web, "ada", OWNER)
    c = browser(); idp.user.update(sub="owner-sub", email=OWNER)
    f = frag(callback(c, at_provider(start(c, ticket_url(c)))))
    assert "oauth_link" in f and "oauth_code" not in f      # never merged on an email match
    ticket = f["oauth_link"][0]
    assert c.post("/auth/link", json={"ticket": ticket, "password": "Wrong1234x"}).status_code == 401
    assert c.post("/auth/link", json={"ticket": ticket, "password": PW}).status_code == 200


def test_cancelling_works_in_test_mode(restricted, idp):
    c = browser(); idp.mode = "cancel"
    assert frag(callback(c, at_provider(start(c, ticket_url(c))))) == {"oauth_error": ["cancelled"]}


def test_signed_in_deletion_check_still_works_for_the_owner(restricted, idp):
    c = browser(); idp.user.update(sub="owner-sub", email=OWNER)
    r = callback(c, at_provider(start(c, ticket_url(c))))
    u = c.post("/auth/exchange", json={"ticket": frag(r)["oauth_code"][0]}).json()
    url = c.post("/account/reauth/google", headers=auth(u["token"])).json()["url"]
    assert c.get(url[len(API):]).status_code == 303          # intent flow needs no test ticket


# ---------------- nothing else changes ----------------

def test_email_password_accounts_are_untouched_in_test_mode(restricted):
    c = browser(); signup(c, "ada", "ada@example.test")
    assert c.post("/login", json={"username": "ada", "password": PW}).status_code == 200
    assert c.post("/login", json={"username": "ada@example.test", "password": PW}).status_code == 200


def test_no_email_address_or_key_is_hardcoded_in_code_or_frontend():
    for name in ("oauth.py", "main.py", "index.html", "about.html", "privacy.html", "terms.html"):
        if not (ROOT / name).exists():          # the public pages arrive via a separate PR
            continue
        text = (ROOT / name).read_text(encoding="utf-8")
        assert not re.search(r"demirelcf|tovdemirel", text, re.I), name
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "GOOGLE_TEST_KEY" not in html and "GOOGLE_TEST_EMAILS" not in html
