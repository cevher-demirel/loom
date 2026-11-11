"""Stage 30 -- the isolated test environment script, including the https mode that
makes Secure cookies behave as they do in production (self-signed cert, loopback)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

import database
import oauth

pytestmark = pytest.mark.browser
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def https_stack(request, monkeypatch, fresh_db):
    sys.path.insert(0, str(ROOT))
    from scripts.oauth_test_env import Stack
    saved_env, saved_google = dict(os.environ), dict(oauth.PROVIDERS["google"])
    saved_db, saved_turso = database.DB_PATH, database.USE_TURSO
    s = Stack(https=True, seed=request.node.get_closest_marker('seed') is not None)
    try:
        yield s
    finally:
        s.close()
        os.environ.clear(); os.environ.update(saved_env)
        oauth.PROVIDERS["google"] = saved_google
        database.DB_PATH, database.USE_TURSO = saved_db, saved_turso


def test_google_login_works_over_https_with_secure_binding_cookie(browser, https_stack):
    s = https_stack
    assert s.api.startswith("https://") and os.path.basename(database.DB_PATH).startswith("loom_stage30_test_")
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, ignore_https_errors=True)
    ctx.add_init_script("try{localStorage.setItem('loominous_returning','1')}catch(e){}")
    seen = []
    ctx.on("response", lambda r: seen.append(r) if "/auth/google/start" in r.url else None)
    page = ctx.new_page()
    page.goto(s.front + "/")
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=15000)
    page.wait_for_timeout(500)
    page.locator("#auth-google-btn").click()
    page.wait_for_function("localStorage.getItem('loom_token')", timeout=15000)
    sc = [h["value"] for r in seen for h in r.headers_array() if h["name"].lower() == "set-cookie"]
    low = sc[0].lower() if sc else ""
    assert "secure" in low and "httponly" in low and "samesite=lax" in low
    assert not any(c["name"].startswith("loom_oauth_") for c in ctx.cookies())      # cleared after callback
    ctx.close()


def test_env_script_refuses_to_start_with_a_production_credential():
    env = dict(os.environ, TURSO_DATABASE_URL="libsql://example.invalid")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "oauth_test_env.py")], env=env,
                       capture_output=True, text=True, timeout=60, cwd=str(ROOT))
    assert r.returncode != 0 and "REFUSING TO START" in (r.stderr + r.stdout)
    assert "libsql://example.invalid" not in (r.stderr + r.stdout)                    # value never echoed


@pytest.mark.seed
def test_seeded_password_account_with_same_email_is_offered_linking_not_merged(browser, https_stack):
    s = https_stack
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, ignore_https_errors=True)
    ctx.add_init_script("try{localStorage.setItem('loominous_returning','1')}catch(e){}")
    page = ctx.new_page()
    page.goto(s.front + "/")
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=15000)
    page.wait_for_timeout(500)
    page.locator("#auth-google-btn").click()
    page.wait_for_selector("#auth-panel-link", state="visible", timeout=15000)
    assert not page.evaluate("localStorage.getItem('loom_token')")           # not signed in, not merged
    page.fill("#link-password", "wrong-password-9")
    page.locator("#link-submit-btn").click()
    page.wait_for_function("document.getElementById('link-status').textContent.length > 0")
    assert not page.evaluate("localStorage.getItem('loom_token')")
    ctx.close()
