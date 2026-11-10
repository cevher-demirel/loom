"""Stage 28 -- new sign-in screen: layout at phone/tablet/desktop widths, keyboard,
show/hide password, provider buttons only when the backend reports them configured,
OAuth return handling (fragment cleaned, ticket exchanged), and link-account flow.
All network is stubbed; no provider or production call is made."""
import json

import pytest

from tests.browser.harness import INDEX

pytestmark = pytest.mark.browser

SIZES = [(320, 568), (375, 667), (390, 844), (430, 932), (768, 1024), (1280, 800)]


def _page(browser, w, h, providers=None, routes=None, hash_="", returning=True):
    ctx = browser.new_context(viewport={"width": w, "height": h}, has_touch=w < 900, is_mobile=w < 900)
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    calls = []
    routes = routes or {}

    def route(r):
        u = r.request.url
        if u.startswith("file:"):
            return r.continue_()
        calls.append((r.request.method, u))
        cors = {"access-control-allow-origin": "*", "access-control-allow-headers": "*"}
        if r.request.method == "OPTIONS":
            return r.fulfill(status=204, headers=cors)
        for suffix, (status, body) in {"/auth/providers": (200, providers or {"google": False, "apple": False}), **routes}.items():
            if u.endswith(suffix):
                return r.fulfill(status=status, content_type="application/json", headers=cors, body=json.dumps(body))
        return r.abort()
    page.route("**/*", route)
    if returning:
        page.add_init_script("localStorage.setItem('loominous_returning','1');")
    base = str(INDEX)
    page.goto((base if base.startswith("file:") else "file://" + base) + hash_)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.wait_for_timeout(500)
    return ctx, page, errs, calls


@pytest.mark.parametrize("w,h", SIZES)
def test_layout_no_overflow_and_core_controls_reachable(browser, w, h):
    ctx, page, errs, _ = _page(browser, w, h)
    assert not page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    for sel in ("#login-username", "#login-password", "#login-btn", "#forgot-password-link", "#login-to-signup-btn"):
        b = page.locator(sel).bounding_box()
        assert b and b["x"] >= 0 and b["x"] + b["width"] <= w + 1, (sel, b)
        assert b["height"] >= 40, (sel, b)  # touch-friendly (44px with the invisible hit area)
    if w <= 430:
        b = page.locator("#login-btn").bounding_box()
        assert b["y"] + b["height"] <= h + 1, "Sign In must be visible without scrolling"
    assert page.locator("#login-btn").inner_text().strip() == "Sign In"
    assert not errs, errs
    ctx.close()


def test_provider_buttons_hidden_when_not_configured(browser):
    ctx, page, _, _ = _page(browser, 390, 844)
    assert page.locator("#auth-providers").is_hidden()
    assert page.locator("#auth-google-btn").is_hidden()
    ctx.close()


def test_only_configured_provider_is_shown(browser):
    ctx, page, _, _ = _page(browser, 390, 844, providers={"google": True, "apple": False})
    page.wait_for_selector("#auth-google-btn", state="visible")
    assert page.locator("#auth-apple-btn").count() == 0
    ctx.close()


def test_provider_buttons_visible_and_hidden_on_other_views(browser):
    ctx, page, _, _ = _page(browser, 390, 844, providers={"google": True, "apple": True})
    page.wait_for_selector("#auth-google-btn", state="visible")
    assert page.locator("#auth-divider").inner_text() == "or continue with"
    page.click("#forgot-password-link")
    assert page.locator("#auth-providers").is_hidden()
    page.click("#forgot-back-btn")
    page.click("#login-to-signup-btn")
    assert page.locator("#auth-providers").is_visible()
    assert page.locator("#signup-username").is_visible()
    page.click("#signup-to-login-btn")
    assert page.locator("#login-username").is_visible()
    ctx.close()


def test_google_button_goes_to_backend_start_url(browser):
    ctx, page, _, calls = _page(browser, 390, 844, providers={"google": True, "apple": True})
    page.wait_for_selector("#auth-google-btn", state="visible")
    page.click("#auth-google-btn")
    page.wait_for_timeout(300)
    assert any(u.endswith("/auth/google/start") for _, u in calls), calls
    ctx.close()


def test_show_hide_password_and_keyboard_order(browser):
    ctx, page, _, _ = _page(browser, 390, 844)
    page.focus("#login-username")
    order = []
    for _ in range(5):
        page.keyboard.press("Tab")
        order.append(page.evaluate("document.activeElement.id || document.activeElement.className"))
    assert order[0] == "login-password"
    assert "password-toggle-btn" in order[1]
    assert order[2] == "forgot-password-link"
    assert order[3] == "login-btn"
    assert order[4] == "login-to-signup-btn"
    page.fill("#login-password", "Secret123x")
    page.focus(".password-toggle-btn[data-password-toggle=login-password]")
    page.keyboard.press("Enter")
    assert page.get_attribute("#login-password", "type") == "text"
    page.keyboard.press("Enter")
    assert page.get_attribute("#login-password", "type") == "password"
    ctx.close()


def test_focus_ring_is_visible_on_fields_and_button(browser):
    ctx, page, _, _ = _page(browser, 390, 844)
    for sel in ("#login-username", "#login-btn"):
        page.focus(sel)
        page.keyboard.press("Shift+Tab")
        page.keyboard.press("Tab")
        assert page.evaluate("getComputedStyle(document.querySelector('%s')).outlineStyle" % sel) != "none", sel
    ctx.close()


def test_wrong_credentials_shows_readable_error_and_re_enables_button(browser):
    ctx, page, _, _ = _page(browser, 390, 844,
                            routes={"/login": (401, {"detail": "Incorrect username or password"})})
    page.fill("#login-username", "nobody")
    page.fill("#login-password", "Wrong1234x")
    page.click("#login-btn")
    page.wait_for_selector("#auth-notice", state="visible")
    assert "Incorrect username or password" in page.inner_text("#auth-notice")
    assert page.is_enabled("#login-btn")
    assert page.get_attribute("#auth-notice", "role") == "alert"
    ctx.close()


def test_oauth_code_in_fragment_is_removed_and_exchanged(browser):
    ctx, page, errs, calls = _page(
        browser, 390, 844, hash_="#oauth_code=ticket123",
        routes={"/auth/exchange": (200, {"token": "tok", "username": "moon"})})
    page.wait_for_timeout(800)
    assert "oauth_code" not in page.evaluate("location.href")
    assert any(m == "POST" and u.endswith("/auth/exchange") for m, u in calls)
    assert page.evaluate("localStorage.getItem('loom_token')") == "tok"
    ctx.close()


def test_oauth_error_in_fragment_shows_message(browser):
    ctx, page, _, _ = _page(browser, 390, 844, hash_="#oauth_error=email_unverified")
    page.wait_for_selector("#auth-notice", state="visible")
    assert "isn't verified" in page.inner_text("#auth-notice")
    assert "oauth_error" not in page.evaluate("location.href")
    ctx.close()


def test_malformed_escape_in_fragment_does_not_break_the_page(browser):
    """A hand-edited address like #oauth_error=%E0%A4%A must not throw and stop the page script."""
    ctx, page, _, _ = _page(browser, 390, 844, hash_="#oauth_x=%E0%A4%A&oauth_error=email_unverified")
    page.wait_for_selector("#auth-notice", state="visible")
    assert "isn't verified" in page.inner_text("#auth-notice")
    ctx.close()


def test_link_flow_requires_password_and_shows_wrong_password(browser):
    ctx, page, _, calls = _page(
        browser, 390, 844, hash_="#oauth_link=lt1&provider=google",
        routes={"/auth/link": (401, {"detail": "That password isn't right"})})
    page.wait_for_selector("#auth-panel-link", state="visible")
    assert page.locator("#auth-panel-login").is_hidden()
    assert "Google" in page.inner_text("#link-note")
    page.fill("#link-password", "Wrong1234x")
    page.click("#link-submit-btn")
    page.wait_for_selector("#auth-notice", state="visible")
    assert "isn't right" in page.inner_text("#auth-notice")
    sent = [u for m, u in calls if u.endswith("/auth/link")]
    assert sent
    page.click("#link-cancel-btn")
    assert page.locator("#auth-panel-login").is_visible()
    ctx.close()


def test_page_does_not_scroll_horizontally_on_sign_up_and_forgot(browser):
    ctx, page, _, _ = _page(browser, 320, 568)
    page.click("#login-to-signup-btn")
    assert not page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    page.click("#signup-to-login-btn")
    page.click("#forgot-password-link")
    assert not page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    ctx.close()


def test_no_apple_anywhere_in_the_interface_even_if_backend_reports_it(browser):
    ctx, page, _, _ = _page(browser, 390, 844, providers={"google": True, "apple": True})
    page.wait_for_selector("#auth-google-btn", state="visible")
    assert "apple" not in page.evaluate("document.getElementById('auth-shell').innerText").lower()
    assert page.locator("#auth-shell [data-provider=apple], #auth-apple-btn").count() == 0
    ctx.close()


@pytest.mark.parametrize("w,h,asset", [(390, 844, "login-mobile.webp"), (1280, 800, "login-desktop.webp")])
def test_real_webp_artwork_is_used_per_breakpoint(browser, w, h, asset):
    ctx, page, _, _ = _page(browser, w, h)
    bg = page.evaluate("getComputedStyle(document.getElementById('auth-panel')).backgroundImage")
    assert asset in bg, bg
    ok = page.evaluate(r"""() => new Promise(res => { const i = new Image();
        i.onload = () => res([i.naturalWidth, i.naturalHeight]); i.onerror = () => res(null);
        i.src = getComputedStyle(document.getElementById('auth-panel')).backgroundImage.match(/url\("?([^")]+)"?\)/)[1]; })""")
    assert ok and ok[0] > 900, ok
    ctx.close()


def test_copy_and_sign_in_button_use_app_palette(browser):
    ctx, page, _, _ = _page(browser, 390, 844)
    assert page.inner_text("#auth-shell .auth-tagline") == "A sacred space for your dreams"
    assert page.inner_text("#auth-panel-login .auth-welcome") == "Welcome Back"
    assert page.inner_text("#login-to-signup-btn") == "Create an account"
    css = page.evaluate("(()=>{const c=getComputedStyle(document.getElementById('login-btn'));return [c.backgroundImage,c.borderTopColor]})()")
    assert "rgb(79, 44, 207)" in css[0] and "rgb(183, 154, 255)" in css[0]   # Home 'Record a dream' gradient stops
    assert css[1] == "rgb(226, 212, 255)"
    ctx.close()


# ---- final polish ---------------------------------------------------------------------------

@pytest.mark.parametrize("w,h", [(375, 812), (390, 844), (430, 932)])
def test_card_leaves_the_moon_visible_on_normal_phones(browser, w, h):
    """The portrait art's moon ends ~21% down the image; on phones of ordinary height
    (live state: no Google button) the card must start below it."""
    ctx, page, _, _ = _page(browser, w, h)
    top = page.evaluate("document.querySelector('.auth-card').getBoundingClientRect().top")
    assert top >= h * 0.21, (top, h * 0.21)
    ctx.close()


@pytest.mark.parametrize("w,h", [(320, 568), (375, 600)])
def test_short_phones_keep_form_on_screen_with_google_shown(browser, w, h):
    ctx, page, _, _ = _page(browser, w, h, providers={"google": True})
    page.wait_for_selector("#auth-google-btn", state="visible")
    assert not page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    b = page.locator("#login-btn").bounding_box()
    assert b["y"] >= 0 and b["y"] + b["height"] <= h + 1
    assert page.evaluate("document.documentElement.scrollHeight") <= h + 2   # no real vertical scroll needed
    ctx.close()


def test_interactive_targets_are_at_least_44px(browser):
    ctx, page, _, _ = _page(browser, 320, 568, providers={"google": True})
    page.wait_for_selector("#auth-google-btn", state="visible")
    for sel in ("#login-username", "#login-password", "#login-btn", "#auth-google-btn"):
        assert page.locator(sel).bounding_box()["height"] >= 44, sel
    for sel in ("#forgot-password-link", "#login-to-signup-btn",
                ".password-toggle-btn[data-password-toggle=login-password]"):
        # links/icons keep a >=44px hit box (padding or min-height)
        assert page.locator(sel).bounding_box()["height"] >= 44 - 0.5, sel
    ctx.close()


def test_hit_areas_of_neighbouring_links_do_not_overlap(browser):
    ctx, page, _, _ = _page(browser, 320, 568, providers={"google": True})
    page.wait_for_selector("#auth-google-btn", state="visible")
    link = page.locator("#login-to-signup-btn").bounding_box()
    btn = page.locator("#login-btn").bounding_box()
    google = page.locator("#auth-google-btn").bounding_box()
    assert link["y"] >= btn["y"] + btn["height"] - 1
    assert link["y"] + link["height"] <= google["y"] + 1
    ctx.close()


def test_labels_autocomplete_and_announcements(browser):
    ctx, page, _, _ = _page(browser, 390, 844)
    assert page.get_attribute("#login-username", "autocomplete") == "username"
    assert page.get_attribute("#login-password", "autocomplete") == "current-password"
    for fid in ("login-username", "login-password"):
        assert page.locator(f"label[for={fid}]").count() == 1
    assert page.get_attribute(".password-toggle-btn[data-password-toggle=login-password]", "aria-label") == "Show password"
    assert page.get_attribute("#login-status", "aria-live") == "polite"
    assert page.get_attribute("#auth-notice", "role") == "alert"
    ctx.close()


def test_reduced_motion_stops_the_spinner_animation_and_overlay_slide(browser):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page = ctx.new_page()
    page.route("**/*", lambda r: r.continue_() if r.request.url.startswith("file:") else r.abort())
    page.add_init_script("localStorage.setItem('loominous_returning','1');")
    base = str(INDEX)
    page.goto(base if base.startswith("file:") else "file://" + base)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    dur = page.evaluate("getComputedStyle(document.getElementById('auth-panel')).transitionDuration")
    assert dur in ("0s", "0s, 0s"), dur
    ctx.close()


@pytest.mark.parametrize("w,h", [(640, 400), (400, 300)])
def test_zoomed_in_viewports_do_not_scroll_sideways_or_clip(browser, w, h):
    """640x400 is 1280x800 at 200% browser zoom; 400x300 is 320x... at 125%-ish extreme."""
    ctx, page, _, _ = _page(browser, w, h)
    assert not page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    for sel in ("#login-username", "#login-password", "#login-btn"):
        b = page.locator(sel).bounding_box()
        assert b["x"] >= 0 and b["x"] + b["width"] <= w + 1, sel
    ctx.close()


def test_artwork_failure_falls_back_to_dark_gradient_and_form_still_works(browser):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    page.route("**/*.webp", lambda r: r.abort())
    page.route("**/*", lambda r: r.continue_() if r.request.url.startswith("file:") else r.abort())
    page.add_init_script("localStorage.setItem('loominous_returning','1');")
    base = str(INDEX)
    page.goto(base if base.startswith("file:") else "file://" + base)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    bg = page.evaluate("getComputedStyle(document.getElementById('auth-panel')).backgroundImage")
    assert "linear-gradient" in bg
    assert page.locator("#login-btn").is_visible()
    ctx.close()


def test_asset_files_exist_and_are_referenced_relative_to_the_page():
    import os, re
    here = os.path.dirname(str(INDEX).replace("file://", ""))
    html = open(os.path.join(here, "index.html"), encoding="utf-8").read()
    for name in ("login-mobile.webp", "login-desktop.webp"):
        assert f'url("assets/login/{name}")' in html
        assert os.path.getsize(os.path.join(here, "assets", "login", name)) > 50_000
    assert not re.search(r'url\("/assets', html)    # no root-absolute path (would break under a /loom/ Pages subpath)
