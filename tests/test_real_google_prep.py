"""
tests/test_real_google_prep.py -- Stage 30 Phase B preparation.

Checks the *inert* wiring of scripts/oauth_test_env.py --real-google: loopback https only, Google's real
authorize endpoint with the exact redirect URI, Secure binding cookie, and refusals. It never contacts
Google (the authorize URL is only inspected, never followed) and uses placeholder credentials.
"""
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

import database
import oauth

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = str(ROOT / "scripts" / "oauth_test_env.py")
FAKE_ID, FAKE_SECRET = "placeholder-id.apps.googleusercontent.com", "placeholder-secret-value"


@pytest.fixture
def real_stack(monkeypatch, fresh_db):
    sys.path.insert(0, str(ROOT))
    from scripts.oauth_test_env import Stack
    saved_env, saved_google = dict(os.environ), dict(oauth.PROVIDERS["google"])
    saved_db, saved_turso = database.DB_PATH, database.USE_TURSO
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    s = Stack(https=True, api_host="localhost", front_host="127.0.0.1", real_google=(FAKE_ID, FAKE_SECRET))
    try:
        yield s
    finally:
        s.close()
        os.environ.clear(); os.environ.update(saved_env)
        oauth.PROVIDERS["google"] = saved_google
        database.DB_PATH, database.USE_TURSO = saved_db, saved_turso


def test_real_mode_uses_googles_real_endpoint_and_the_exact_local_redirect_uri(real_stack):
    s = real_stack
    assert s.idp is None and s.api.startswith("https://localhost:") and s.front.startswith("https://127.0.0.1:")
    assert oauth.PROVIDERS["google"]["authorize"].startswith("https://accounts.google.com/")   # not replaced by a mock
    c = httpx.Client(verify=False, follow_redirects=False, timeout=10)         # self-signed cert, loopback only
    assert c.get(s.api + "/auth/providers").json()["google"] is True
    r = c.get(s.api + "/auth/google/start")
    assert r.status_code == 303
    u = urlparse(r.headers["location"]); q = parse_qs(u.query)
    assert u.scheme == "https" and u.netloc == "accounts.google.com"
    assert q["redirect_uri"] == [s.api + "/auth/google/callback"]
    assert q["client_id"] == [FAKE_ID] and q["code_challenge_method"] == ["S256"]
    assert "client_secret" not in r.headers["location"] and FAKE_SECRET not in r.headers["location"]
    sc = r.headers["set-cookie"].lower()
    assert "secure" in sc and "httponly" in sc and "samesite=lax" in sc and "domain=" not in sc


def test_real_mode_is_cross_site_like_production(real_stack):
    """Frontend on 127.0.0.1, backend on localhost: different sites, as loominous.org vs the Render host."""
    assert urlparse(real_stack.front).hostname != urlparse(real_stack.api).hostname


def _run(*args, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("TURSO_DATABASE_URL", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "PUBLIC_API_BASE", "FRONTEND_URL")}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, SCRIPT, *args], env=env, capture_output=True, text=True,
                          timeout=60, cwd=str(ROOT), stdin=subprocess.DEVNULL)


def test_real_mode_refuses_without_https():
    r = _run("--real-google")
    assert r.returncode != 0 and "requires --https" in r.stderr + r.stdout


def test_real_mode_refuses_when_credentials_are_in_the_environment_and_never_echoes_them():
    r = _run("--real-google", "--https", env_extra={"GOOGLE_CLIENT_SECRET": "super-secret-123"})
    assert r.returncode != 0 and "REFUSING TO START" in r.stderr + r.stdout
    assert "super-secret-123" not in r.stderr + r.stdout


def test_real_mode_refuses_with_a_production_database_credential():
    r = _run("--real-google", "--https", env_extra={"TURSO_DATABASE_URL": "libsql://example.invalid"})
    assert r.returncode != 0 and "REFUSING TO START" in r.stderr + r.stdout
    assert "libsql://example.invalid" not in r.stderr + r.stdout


def test_real_mode_refuses_to_combine_with_seed_and_waits_for_explicit_yes():
    assert _run("--real-google", "--https", "--seed").returncode != 0
    r = _run("--real-google", "--https")                  # no stdin: the confirmation prompt gets EOF and aborts
    assert r.returncode != 0 and "https://localhost:8444/auth/google/callback" in r.stdout
    assert "onrender.com" not in r.stdout and "loom-phas" not in r.stdout


def test_stack_rejects_non_loopback_hosts_and_missing_https():
    sys.path.insert(0, str(ROOT))
    from scripts.oauth_test_env import Stack
    with pytest.raises(AssertionError):
        Stack(https=True, api_host="loom-phas.onrender.com", real_google=(FAKE_ID, FAKE_SECRET))
    with pytest.raises(AssertionError):
        Stack(https=False, real_google=(FAKE_ID, FAKE_SECRET))


def test_script_contains_no_credentials_or_production_hosts():
    text = Path(SCRIPT).read_text()
    assert "GOCSPX" not in text and "googleusercontent.com\"" not in text
    assert "loom-phas.onrender.com" in text                    # only as the string it replaces in the temp page copy
    assert "onrender.com\" in cid" in text                      # and a guard against pasting a Render URL as a credential
