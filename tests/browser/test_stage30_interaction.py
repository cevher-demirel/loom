"""Stage 30 -- real-pointer interaction. No dispatch_event, no force=True: every
control is reached with an ordinary Playwright click/tap, at the widths the app
supports. Backend, page and identity provider are the local ones from the
Stage 29 e2e stack (throwaway DB, mock Google, loopback only)."""
import pytest

from tests.browser.test_stage29_google_e2e import stack, _open, _signed_in  # noqa: F401

pytestmark = pytest.mark.browser

WIDTHS = [(320, 640), (375, 667), (390, 844), (430, 932), (768, 1024), (1280, 800), (1440, 900), (1920, 1080)]


def _ctx(browser, w, h, slow_frames=0):
    touch = w < 900
    ctx = browser.new_context(viewport={"width": w, "height": h}, has_touch=touch, is_mobile=touch)
    ctx.add_init_script("try{localStorage.setItem('loominous_returning','1')}catch(e){}")
    if slow_frames:
        # Simulates a busy/background tab: animation frames arrive late.
        ctx.add_init_script("(function(){var r=window.requestAnimationFrame;window.requestAnimationFrame=function(f){return setTimeout(function(){r(f)},%d)}})()" % slow_frames)
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    return ctx, page, errs


def _press(loc):
    """The way a person would: tap on touch devices, click otherwise."""
    page_touch = loc.page.evaluate("matchMedia('(pointer: coarse)').matches")
    (loc.tap if page_touch else loc.click)(timeout=8000)


def _open_settings_account(page):
    # Phone: the Settings gear lives in the header of the Journal/Home views;
    # desktop: in the side nav. Use whichever is actually visible.
    gear = page.locator("[data-tab=profile]:visible")
    if gear.count() == 0:                       # phone Home has no header: go via the Journal tab
        _press(page.locator("[data-tab=archive]:visible").first)
        page.wait_for_selector("[data-tab=profile]:visible")
    gear = gear.first
    _press(gear)
    _press(page.locator("#settings-go-account-btn"))
    page.wait_for_selector("#settings-account-view", state="visible")


def test_app_stays_clickable_when_sign_in_beats_the_overlay_animation(browser, stack):
    """Regression: with late animation frames, finishing sign-in before the
    sign-in overlay had finished opening left #app-shell permanently inert
    (pointer-events:none), so Settings could not be clicked."""
    ctx, page, errs = _ctx(browser, 1280, 800, slow_frames=400)
    _open(page, stack)
    page.click("#auth-google-btn")
    _signed_in(page)
    page.wait_for_timeout(1500)
    assert page.evaluate("getComputedStyle(document.getElementById('app-shell')).pointerEvents") != "none"
    _press(page.locator("[data-tab=profile]:visible").first)
    page.wait_for_selector("#settings-account-view, #settings-go-account-btn", state="visible", timeout=5000)
    assert not errs, errs
    ctx.close()


@pytest.mark.parametrize("w,h", WIDTHS)
def test_settings_to_delete_prompt_with_real_clicks(browser, stack, w, h):
    ctx, page, errs = _ctx(browser, w, h)
    _open(page, stack)
    _press(page.locator("#auth-google-btn"))
    _signed_in(page)
    _open_settings_account(page)
    _press(page.locator("#delete-account-btn"))
    page.wait_for_selector("#delete-account-google-btn", state="visible")
    assert page.locator("#delete-account-password").is_hidden()
    _press(page.locator("#delete-account-cancel-btn"))        # cancel returns to the account screen
    page.wait_for_selector("#delete-account-btn", state="visible")
    assert page.locator("#delete-account-confirm").is_hidden()
    assert not errs, errs
    ctx.close()


# ---------- account deletion, every path, real clicks ----------
import sqlite3

import httpx

import database

PW = "Moonlit9pond"


def _count(table):
    c = sqlite3.connect(database.DB_PATH)
    try:
        return c.execute("select count(*) from %s" % table).fetchone()[0]
    finally:
        c.close()


def _password_login(page, name):
    page.fill("#login-username", name)
    page.fill("#login-password", PW)
    _press(page.locator("#login-btn"))
    _signed_in(page)


def _make_password_user(stack, name="pwuser", email="pw@example.test"):
    r = httpx.post(stack.api + "/signup", json={"username": name, "email": email, "password": PW}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("w,h", [(390, 844), (1280, 800)])
def test_password_account_deletion_with_real_clicks(browser, stack, w, h):
    _make_password_user(stack)
    ctx, page, errs = _ctx(browser, w, h)
    _open(page, stack)
    _password_login(page, "pwuser")
    _open_settings_account(page)
    _press(page.locator("#delete-account-btn"))
    page.wait_for_selector("#delete-account-password", state="visible")
    assert page.locator("#delete-account-google").is_hidden()          # no Google option without a Google identity
    page.fill("#delete-account-password", "wrong-password-1")
    _press(page.locator("#delete-account-confirm-btn"))
    page.wait_for_function("document.getElementById('delete-account-status').textContent.length > 0")
    assert _count("users") == 1                                         # wrong password deletes nothing
    assert page.evaluate("localStorage.getItem('loom_token')")         # and does not look like an expired session
    page.fill("#delete-account-password", PW)
    _press(page.locator("#delete-account-confirm-btn"))
    page.wait_for_function("!localStorage.getItem('loom_token')", timeout=10000)
    assert _count("users") == 0
    assert not errs, errs
    ctx.close()


@pytest.mark.parametrize("w,h", [(390, 844), (1280, 800)])
def test_google_only_deletion_full_flow_with_real_clicks(browser, stack, w, h):
    ctx, page, errs = _ctx(browser, w, h)
    _open(page, stack)
    _press(page.locator("#auth-google-btn"))
    _signed_in(page)
    _open_settings_account(page)
    _press(page.locator("#delete-account-btn"))
    # 1) start Google verification, then cancel at Google
    stack.idp.mode = "cancel"
    _press(page.locator("#delete-account-google-btn"))
    page.wait_for_function("document.getElementById('delete-account-status').textContent.includes('not deleted')", timeout=10000)
    assert _count("users") == 1 and page.evaluate("localStorage.getItem('loom_token')")
    # 2) back on the account screen; verify properly this time
    stack.idp.mode = "approve"
    _press(page.locator("#delete-account-btn"))
    _press(page.locator("#delete-account-google-btn"))
    page.wait_for_selector("#delete-account-google-final-btn", state="visible", timeout=10000)
    assert _count("users") == 1                                         # verified, still nothing deleted
    # 3) Cancel after verifying keeps the account and drops the one-time proof
    _press(page.locator("#delete-account-cancel-btn"))
    assert _count("users") == 1
    assert page.locator("#delete-account-google-final-btn").is_hidden()
    # 4) once more, then the explicit final click
    _press(page.locator("#delete-account-btn"))
    _press(page.locator("#delete-account-google-btn"))
    page.wait_for_selector("#delete-account-google-final-btn", state="visible", timeout=10000)
    _press(page.locator("#delete-account-google-final-btn"))
    page.wait_for_function("!localStorage.getItem('loom_token')", timeout=10000)
    assert _count("users") == 0 and _count("auth_identities") == 0
    assert page.locator("#login-btn").is_visible()
    assert not errs, errs
    ctx.close()


def test_wrong_google_identity_cannot_delete(browser, stack):
    ctx, page, errs = _ctx(browser, 1280, 800)
    _open(page, stack)
    _press(page.locator("#auth-google-btn"))
    _signed_in(page)
    _open_settings_account(page)
    _press(page.locator("#delete-account-btn"))
    stack.idp.user = dict(stack.idp.user, sub="someone-else", email="other@example.test")
    _press(page.locator("#delete-account-google-btn"))
    page.wait_for_function("document.getElementById('delete-account-status').textContent.includes('not deleted')", timeout=10000)
    assert "isn't the Google account" in page.inner_text("#delete-account-status")
    assert _count("users") == 1 and _count("auth_identities") == 1
    ctx.close()


def test_account_with_both_methods_offers_both(browser, stack):
    _make_password_user(stack, "both", "both@example.test")
    c = sqlite3.connect(database.DB_PATH)
    uid = c.execute("select id from users where username='both'").fetchone()[0]
    c.close()
    database.link_identity(uid, "google", "both-sub", "both@example.test")
    ctx, page, errs = _ctx(browser, 1280, 800)
    _open(page, stack)
    _password_login(page, "both")
    _open_settings_account(page)
    _press(page.locator("#delete-account-btn"))
    page.wait_for_selector("#delete-account-password", state="visible")
    assert page.locator("#delete-account-google-btn").is_visible()
    assert _count("users") == 1
    ctx.close()


def test_expired_google_verification_is_refused_and_account_survives(browser, stack, monkeypatch):
    ctx, page, errs = _ctx(browser, 1280, 800)
    _open(page, stack)
    _press(page.locator("#auth-google-btn"))
    _signed_in(page)
    _open_settings_account(page)
    _press(page.locator("#delete-account-btn"))
    _press(page.locator("#delete-account-google-btn"))
    page.wait_for_selector("#delete-account-google-final-btn", state="visible", timeout=10000)
    from datetime import timedelta
    monkeypatch.setattr(database, "OAUTH_TICKET_LIFETIME", timedelta(seconds=-1))   # proof is now older than allowed
    _press(page.locator("#delete-account-google-final-btn"))
    page.wait_for_function("document.getElementById('delete-account-status').textContent.length > 0", timeout=10000)
    assert _count("users") == 1
    assert page.evaluate("localStorage.getItem('loom_token')")
    assert page.locator("#delete-account-google-btn").is_visible()      # offered a fresh verification
    ctx.close()


def test_expired_session_during_deletion_returns_to_sign_in_without_deleting(browser, stack):
    ctx, page, errs = _ctx(browser, 1280, 800)
    _open(page, stack)
    _press(page.locator("#auth-google-btn"))
    _signed_in(page)
    _open_settings_account(page)
    _press(page.locator("#delete-account-btn"))
    page.wait_for_selector("#delete-account-google-btn", state="visible")
    c = sqlite3.connect(database.DB_PATH)
    c.execute("update users set token=null"); c.commit(); c.close()
    _press(page.locator("#delete-account-google-btn"))
    page.wait_for_function("document.getElementById('delete-account-status').textContent.length > 0", timeout=10000)
    assert _count("users") == 1 and _count("auth_identities") == 1
    ctx.close()
