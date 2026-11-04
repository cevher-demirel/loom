"""Stage 23h -- splash timing, auth defaults/targets, account deletion presentation and safeguards, narrow tray title."""
import time

import pytest

from tests.browser.harness import INDEX, make, to_explorer, pick_child
from tests.browser.seed import dreams

pytestmark = pytest.mark.browser


def _anon(browser, w=390, h=844, returning=False, reduced=False):
    ctx = browser.new_context(viewport={"width": w, "height": h}, has_touch=True, is_mobile=True,
                              reduced_motion="reduce" if reduced else "no-preference")
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    # block the network entirely: the auth screen needs none of it
    page.route("**/*", lambda r: r.continue_() if r.request.url.startswith("file:") else r.abort())
    if returning:
        page.add_init_script("localStorage.setItem('loominous_returning','1');")
    page.goto("file://" + INDEX if not str(INDEX).startswith("file:") else str(INDEX))
    return ctx, page, errs


def test_splash_is_shorter_and_skippable(browser):
    ctx, page, errs = _anon(browser)
    t0 = time.time()
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=6000)
    assert time.time() - t0 < 2.0                                  # was ~2.2s+ (1.7s hold + 0.5s fade)
    ctx.close()
    ctx, page, errs = _anon(browser)
    page.wait_for_timeout(250)
    t0 = time.time()
    page.evaluate("document.getElementById('app-splash').dispatchEvent(new PointerEvent('pointerdown', {bubbles: true}))")
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=3000)
    assert time.time() - t0 < 0.9                                  # tap skips the hold (only the short fade remains)
    ctx.close()


def test_reduced_motion_splash_still_brief(browser):
    ctx, page, errs = _anon(browser, reduced=True)
    t0 = time.time()
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=4000)
    assert time.time() - t0 < 1.2
    ctx.close()


def test_first_visit_lands_on_sign_up_and_returning_on_log_in(browser):
    ctx, page, errs = _anon(browser)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=6000)
    assert page.get_attribute("#auth-tab-signup-btn", "aria-selected") == "true"
    ctx.close()
    ctx, page, errs = _anon(browser, returning=True)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=6000)
    assert page.get_attribute("#auth-tab-login-btn", "aria-selected") == "true"
    assert page.locator("#auth-panel-login").is_visible()
    assert errs == []
    ctx.close()


@pytest.mark.parametrize("w,h", [(320, 568), (375, 667), (390, 844)])
def test_login_screen_controls_are_reachable_and_44px(browser, w, h):
    ctx, page, errs = _anon(browser, w, h, returning=True)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=6000)
    page.wait_for_timeout(300)
    b = page.locator("#login-btn").bounding_box()
    assert b["y"] + b["height"] <= h + 1, ("Log In button must be on screen without scrolling", b)
    for sel in ("#forgot-password-link", ".password-toggle-btn[data-password-toggle=login-password]"):
        r = page.evaluate("""(sel) => { const e = document.querySelector(sel); const r = e.getBoundingClientRect();
            const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
            const owns = (x, y) => { const t = document.elementFromPoint(x, y); return !!t && (t === e || e.contains(t)); };
            return {w: r.width, h: r.height, ok: (r.width >= 44 || (owns(cx - 21, cy) && owns(cx + 21, cy))) && (r.height >= 44 || (owns(cx, cy - 21) && owns(cx, cy + 21)))}; }""", sel)
        assert r["ok"], (sel, r)
    # password visibility toggle still works
    page.click(".password-toggle-btn[data-password-toggle=login-password]")
    assert page.get_attribute("#login-password", "type") == "text"
    ctx.close()


def test_account_deletion_is_distinct_and_keeps_every_safeguard(browser):
    ctx, page, st = make(browser, width=390, height=844, dreams=dreams(3))
    deletes = []
    page.on("request", lambda r: deletes.append(r.url) if r.method == "DELETE" and r.url.endswith("/account") else None)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.evaluate("document.querySelector('.header-gear-btn, #home-link-settings').click()")
    page.wait_for_timeout(600)
    page.click("#settings-go-account-btn")
    page.wait_for_timeout(500)
    zone = page.locator(".danger-zone")
    zone.scroll_into_view_if_needed()
    assert "Delete account" in zone.inner_text() and "every dream" in zone.inner_text()
    assert page.locator("#delete-account-btn").get_attribute("class") == "danger-btn"
    assert not page.locator("#delete-account-confirm").is_visible()           # nothing destructive is one tap away
    page.click("#delete-account-btn")
    page.wait_for_timeout(300)
    assert page.locator("#delete-account-confirm").is_visible() and page.locator("#delete-account-password").is_visible()
    page.click("#delete-account-confirm-btn")                                 # no password => nothing is sent
    page.wait_for_timeout(400)
    assert "password" in page.inner_text("#delete-account-status").lower()
    assert deletes == []
    ctx.close()


def test_narrow_tray_title_is_short(browser):
    ctx, page, st = make(browser, width=320, height=568)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    to_explorer(page, "A key.")
    pick_child(page, "fear", 0, 0)
    pick_child(page, "trust", 0, 0)
    page.wait_for_timeout(300)
    assert page.locator(".feel-tray-toggle h4").inner_text().strip() == "Selected (2)"
    ctx.close()
