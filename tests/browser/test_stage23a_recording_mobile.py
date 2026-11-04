"""Stage 23a -- the recording journey on short, rotated and keyboard-constrained viewports."""
import pytest

from tests.browser.harness import make, pick_child, to_explorer

pytestmark = pytest.mark.browser

VIEWPORTS = [(320, 568), (375, 667), (390, 600), (390, 844), (430, 932), (844, 390), (390, 420), (1280, 800)]
LANDSCAPE = (844, 390)


def _visible_in_viewport(page, sel):
    b = page.locator(sel).bounding_box()
    vp = page.viewport_size
    return bool(b) and b["x"] >= -1 and b["y"] >= -1 and b["x"] + b["width"] <= vp["width"] + 1 and b["y"] + b["height"] <= vp["height"] + 1


def _no_hscroll(page):
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


@pytest.mark.parametrize("w,h", VIEWPORTS)
def test_record_continue_is_reachable_while_typing(browser, w, h):
    ctx, page, st = make(browser, width=w, height=h)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.evaluate("document.getElementById('home-record-btn').click()")
    page.fill("#dream-input", "A brass key in a long hallway of doors. " * 3)
    page.wait_for_timeout(400)
    assert _no_hscroll(page)
    page.click("#interpret-btn", timeout=5000)           # fails if covered by nav/keyboard area
    page.wait_for_selector(".feel-wheel")
    ctx.close()


@pytest.mark.parametrize("w,h", [(390, 420), (390, 600)])
def test_record_continue_is_fully_visible_on_short_viewports(browser, w, h):
    ctx, page, st = make(browser, width=w, height=h)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.evaluate("document.getElementById('home-record-btn').click()")
    page.fill("#dream-input", "Typing a dream.")
    page.wait_for_timeout(400)
    assert _visible_in_viewport(page, "#interpret-btn"), page.locator("#interpret-btn").bounding_box()
    assert page.locator("#dream-input").input_value() == "Typing a dream."
    assert _visible_in_viewport(page, "#journal-record-back-btn")           # a way out stays on screen
    ctx.close()


def test_compact_typing_restores_navigation_after_leaving(browser):
    ctx, page, st = make(browser, width=390, height=420)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.evaluate("document.getElementById('home-record-btn').click()")
    page.fill("#dream-input", "text")
    page.wait_for_timeout(300)
    assert page.evaluate("document.body.classList.contains('compose-compact')")
    assert not page.locator(".bottom-tabs").is_visible()
    page.click("#journal-record-back-btn")
    page.wait_for_timeout(500)
    assert not page.evaluate("document.body.classList.contains('compose-compact')")
    assert page.locator(".bottom-tabs").is_visible()
    ctx.close()


def test_draft_and_selection_survive_compact_flow(browser):
    ctx, page, st = make(browser, width=390, height=420)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    to_explorer(page, "My draft survives.")
    pick_child(page, "fear", 0, 0)
    page.click("#feel-back-btn")
    assert page.locator("#dream-input").input_value() == "My draft survives."
    page.click("#interpret-btn")
    page.wait_for_selector(".feel-wheel")
    assert page.locator("#feel-go-btn").inner_text().strip().endswith("(1)")
    ctx.close()


@pytest.mark.parametrize("w,h", VIEWPORTS)
def test_explorer_primary_action_and_wheel_usable(browser, w, h):
    ctx, page, st = make(browser, width=w, height=h)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    to_explorer(page, "A key.")
    page.wait_for_timeout(500)
    assert _no_hscroll(page)
    wb = page.locator(".feel-wheel").bounding_box()
    assert wb and wb["height"] >= 120 and wb["width"] >= 120, wb          # the wheel is actually there
    pick_child(page, "fear", 0, 0)
    pick_child(page, "trust", 0, 0)
    page.wait_for_timeout(400)
    assert _visible_in_viewport(page, "#feel-go-btn"), page.locator("#feel-go-btn").bounding_box()
    assert _visible_in_viewport(page, "#feel-back-btn") and _visible_in_viewport(page, "#feel-skip-btn")
    page.click("#feel-go-btn")
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    assert st["bodies"][-1]["emotions_reported"]
    assert page.evaluate("!document.body.classList.contains('feel-open')")
    ctx.close()


def test_landscape_explorer_layout_and_nav_return(browser):
    w, h = LANDSCAPE
    ctx, page, st = make(browser, width=w, height=h)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    to_explorer(page, "A key.")
    page.click('path[data-feel-family="fear"]', force=True)
    page.wait_for_timeout(500)
    wheel, panel = page.locator(".feel-wheel").bounding_box(), page.locator("#feel-panel").bounding_box()
    assert wheel["x"] + wheel["width"] <= panel["x"] + 2, "wheel and details sit side by side"
    assert not page.locator(".bottom-tabs").is_visible()                      # compact mode drops the nav...
    assert _visible_in_viewport(page, "#feel-back-btn")                       # ...but Back stays on screen
    # details scroll independently; the page itself does not scroll (no nested scroll trap)
    assert page.evaluate("document.documentElement.scrollHeight <= window.innerHeight + 1")
    assert page.evaluate("document.getElementById('feel-panel').scrollHeight >= document.getElementById('feel-panel').clientHeight")
    page.click("#feel-back-btn")
    page.wait_for_timeout(400)
    assert page.evaluate("!document.body.classList.contains('feel-open')")    # explorer layout released
    page.click("#journal-record-back-btn")                                    # leave the record screen
    page.wait_for_timeout(500)
    assert not page.evaluate("document.body.classList.contains('compose-compact')")
    assert page.locator(".bottom-tabs").is_visible()                          # nav is back
    ctx.close()


def test_landscape_rotation_back_to_portrait_restores_layout(browser):
    ctx, page, st = make(browser, width=844, height=390)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    to_explorer(page, "A key.")
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(600)
    assert page.locator(".bottom-tabs").is_visible()
    assert _visible_in_viewport(page, "#feel-back-btn")
    ctx.close()


def test_reduced_motion_landscape_flow(browser):
    ctx, page, st = make(browser, width=844, height=390, reduced=True)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    to_explorer(page, "A key.")
    pick_child(page, "sad", 0, 0)
    page.click("#feel-go-btn")
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    ctx.close()
