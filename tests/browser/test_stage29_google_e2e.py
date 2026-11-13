"""Stage 29 -- the real index.html against the real FastAPI app and a local mock
Google (tests/mock_idp.py). Nothing here touches Google, Render, Turso or any
production data: throwaway SQLite, placeholder credentials, loopback only.
This proves the browser/backend wiring; it is NOT a test against real Google."""
import http.server
import re
import shutil
import socket
import threading

import pytest
import uvicorn

import database
import main
import oauth
from tests.browser.harness import INDEX
from tests.mock_idp import CLIENT_ID, CLIENT_SECRET, MockIdP

pytestmark = pytest.mark.browser
from pathlib import Path


def _port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture
def stack(monkeypatch, fresh_db, tmp_path):
    idp = MockIdP()
    bport, fport = _port(), _port()
    api, front = f"http://127.0.0.1:{bport}", f"http://127.0.0.1:{fport}"
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("PUBLIC_API_BASE", api)
    monkeypatch.setenv("FRONTEND_URL", front)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setitem(oauth.PROVIDERS, "google", idp.provider_config())
    # A temp copy of the real page, pointed at the local backend.
    src = Path(INDEX[len("file://"):]) if INDEX.startswith("file://") else Path(INDEX)
    root = tmp_path / "site"; root.mkdir()
    html = src.read_text()
    assert 'var API_BASE = "https://api.loominous.org";' in html
    (root / "index.html").write_text(html.replace('https://api.loominous.org', api))
    shutil.copytree(src.parent / "assets", root / "assets")

    class Q(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k): super().__init__(*a, directory=str(root), **k)
        def log_message(self, *a): pass
    fsrv = http.server.ThreadingHTTPServer(("127.0.0.1", fport), Q)
    threading.Thread(target=fsrv.serve_forever, daemon=True).start()
    srv = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=bport, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True); t.start()
    while not srv.started:
        pass
    yield type("S", (), {"idp": idp, "api": api, "front": front})
    srv.should_exit = True; t.join(5)
    fsrv.shutdown(); idp.close()


def _ctx(browser, s):
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    ctx.add_init_script("try{localStorage.setItem('loominous_returning','1')}catch(e){}")
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    return ctx, page, errs


def _open(page, s):
    page.goto(s.front + "/")
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=10000)
    page.wait_for_timeout(400)


def _signed_in(page):
    page.wait_for_function("localStorage.getItem('loom_token')", timeout=10000)
    page.wait_for_function("document.getElementById('app-splash').hidden === true || getComputedStyle(document.getElementById('app-splash')).display === 'none' || getComputedStyle(document.getElementById('app-splash')).pointerEvents === 'none'", timeout=10000)
    page.wait_for_timeout(800)


def _google_login(page, s):
    page.click("#auth-google-btn")
    _signed_in(page)


def test_google_button_hidden_until_configured(browser, stack, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "")
    ctx, page, errs = _ctx(browser, stack)
    _open(page, stack)
    assert page.locator("#auth-google-btn").is_hidden()
    ctx.close()
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", CLIENT_SECRET)
    ctx, page, errs = _ctx(browser, stack)
    _open(page, stack)
    assert page.locator("#auth-google-btn").is_visible()
    assert not errs, errs
    ctx.close()


def test_full_login_creates_one_account_and_url_is_cleaned(browser, stack):
    ctx, page, errs = _ctx(browser, stack)
    _open(page, stack)
    _google_login(page, stack)
    assert "oauth_" not in page.url and "code" not in page.url
    me = page.evaluate("fetch(%r+'/account',{headers:{Authorization:'Bearer '+localStorage.getItem('loom_token')}}).then(r=>r.json())" % stack.api)
    assert me["google_linked"] is True and me["has_password"] is False
    assert not errs, errs
    ctx.close()


def test_cancel_at_google_returns_to_sign_in_with_message(browser, stack):
    stack.idp.mode = "cancel"
    ctx, page, errs = _ctx(browser, stack)
    _open(page, stack)
    page.click("#auth-google-btn")
    page.wait_for_url(re.compile(r"^http://127\.0\.0\.1:\d+/(#.*)?$"))
    page.wait_for_timeout(800)
    assert not page.evaluate("localStorage.getItem('loom_token')")
    assert page.locator("#login-btn").is_visible()
    assert "oauth_" not in page.url
    ctx.close()


def test_other_browser_cannot_complete_victims_login(browser, stack):
    """Attacker starts a login, hands the callback URL to the victim's browser."""
    atk_ctx, atk, _ = _ctx(browser, stack)
    vic_ctx, vic, verrs = _ctx(browser, stack)
    _open(atk, stack); _open(vic, stack)
    # The attacker's browser starts a login and stops at Google's redirect back
    # (so the one-time callback URL is never used by the attacker's own browser).
    r1 = atk_ctx.request.get(stack.api + "/auth/google/start", max_redirects=0)
    assert r1.status == 303 and "loom_oauth_" in r1.headers["set-cookie"]
    r2 = atk_ctx.request.get(r1.headers["location"], max_redirects=0)
    cb = {"url": r2.headers["location"]}
    vic.goto(cb["url"])                     # victim has no binding cookie for this flow
    vic.wait_for_timeout(1000)
    assert not vic.evaluate("localStorage.getItem('loom_token')")
    assert vic.locator('#login-btn').is_visible()
    atk_ctx.close(); vic_ctx.close()


def test_google_only_account_deletion_end_to_end(browser, stack):
    ctx, page, errs = _ctx(browser, stack)
    _open(page, stack)
    _google_login(page, stack)
    page.locator(".side-nav-btn--gear").click()
    page.locator("#settings-go-account-btn").click()
    page.locator("#delete-account-btn").click()
    page.wait_for_selector("#delete-account-google-btn", state="visible")
    assert page.locator("#delete-account-password").is_hidden()
    assert "no undo" in page.inner_text("#delete-account-note").lower()
    page.locator("#delete-account-google-btn").click()
    # Back from Google: nothing deleted yet; explicit final button appears.
    page.wait_for_selector("#delete-account-google-final-btn", state="visible", timeout=10000)
    assert page.evaluate("localStorage.getItem('loom_token')")
    me = page.evaluate("fetch(%r+'/account',{headers:{Authorization:'Bearer '+localStorage.getItem('loom_token')}}).then(r=>r.status)" % stack.api)
    assert me == 200
    # Google was asked to re-authenticate.
    assert stack.idp.authorize_requests[-1].get("prompt") == "login"
    page.locator("#delete-account-google-final-btn").click()
    page.wait_for_function("!localStorage.getItem('loom_token')", timeout=10000)
    assert page.locator("#login-btn").is_visible()
    assert not errs, errs
    import sqlite3
    c = sqlite3.connect(database.DB_PATH)
    assert c.execute("select count(*) from users").fetchone()[0] == 0
    assert c.execute("select count(*) from auth_identities").fetchone()[0] == 0
    ctx.close()


def test_deletion_cancelled_at_google_keeps_account(browser, stack):
    ctx, page, errs = _ctx(browser, stack)
    _open(page, stack)
    _google_login(page, stack)
    stack.idp.mode = "cancel"
    page.locator(".side-nav-btn--gear").click()
    page.locator("#settings-go-account-btn").click()
    page.locator("#delete-account-btn").click()
    page.locator("#delete-account-google-btn").click()
    page.wait_for_function("document.getElementById('delete-account-status').textContent.includes('not deleted')", timeout=10000)
    # The message must actually be visible (it once sat inside a hidden panel), with a way to retry.
    assert page.locator("#delete-account-status").is_visible()
    assert page.locator("#delete-account-google-btn").is_visible()
    assert page.evaluate("localStorage.getItem('loom_token')")
    import sqlite3
    assert sqlite3.connect(database.DB_PATH).execute("select count(*) from users").fetchone()[0] == 1
    ctx.close()


def _start_google_deletion(page, stack):
    page.locator(".side-nav-btn--gear").click()
    page.locator("#settings-go-account-btn").click()
    page.locator("#delete-account-btn").click()
    page.locator("#delete-account-google-btn").click()


def test_deletion_works_when_google_omits_auth_time(browser, stack):
    """Real Google never sends auth_time; this was the production bug."""
    ctx, page, errs = _ctx(browser, stack)
    _open(page, stack)
    _google_login(page, stack)
    stack.idp.auth_age = None
    _start_google_deletion(page, stack)
    page.wait_for_selector("#delete-account-google-final-btn", state="visible", timeout=10000)
    page.locator("#delete-account-google-final-btn").click()
    page.wait_for_function("!localStorage.getItem('loom_token')", timeout=10000)
    assert page.locator("#login-btn").is_visible()
    import sqlite3
    assert sqlite3.connect(database.DB_PATH).execute("select count(*) from users").fetchone()[0] == 0
    ctx.close()


def test_failed_google_verification_shows_a_visible_error(browser, stack):
    ctx, page, errs = _ctx(browser, stack)
    _open(page, stack)
    _google_login(page, stack)
    stack.idp.auth_age = 3600                    # Google reports a stale sign-in: verification refused
    _start_google_deletion(page, stack)
    page.wait_for_function("document.getElementById('delete-account-status').textContent.includes('not deleted')", timeout=10000)
    assert page.locator("#delete-account-status").is_visible()
    assert "verify again" in page.inner_text("#delete-account-status").lower()
    assert page.locator("#delete-account-google-btn").is_visible()
    assert page.locator("#delete-account-google-final-btn").is_hidden()
    assert page.evaluate("localStorage.getItem('loom_token')")
    import sqlite3
    assert sqlite3.connect(database.DB_PATH).execute("select count(*) from users").fetchone()[0] == 1
    ctx.close()


def test_wrong_google_account_shows_a_visible_error_and_deletes_nothing(browser, stack):
    ctx, page, errs = _ctx(browser, stack)
    _open(page, stack)
    _google_login(page, stack)
    stack.idp.user.update(sub="someone-elses-google-sub", email="someone@example.test")
    _start_google_deletion(page, stack)
    page.wait_for_function("document.getElementById('delete-account-status').textContent.includes('isn')", timeout=10000)
    assert page.locator("#delete-account-status").is_visible()
    assert "isn't the google account linked" in page.inner_text("#delete-account-status").lower()
    import sqlite3
    assert sqlite3.connect(database.DB_PATH).execute("select count(*) from users").fetchone()[0] == 1
    ctx.close()
