"""Stage 21 -- the browser never creates a second dream for one submission."""
import pytest

from tests.browser.harness import make, to_explorer, pick_child

pytestmark = pytest.mark.browser


def _go(page):
    page.click("#feel-go-btn")


def _setup(browser, **kw):
    ctx, page, st = make(browser, **kw)
    to_explorer(page, "A brass key in a hallway.")
    pick_child(page, "fear", 0, 0)
    return ctx, page, st


def test_normal_submit_sends_one_request_id_and_saves_once(browser):
    ctx, page, st = _setup(browser)
    _go(page)
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    assert len(st["bodies"]) == 1 and len(st["dreams"]) == 1
    assert st["bodies"][0]["request_id"].startswith("sub-")
    ctx.close()


def test_double_click_does_not_double_submit(browser):
    ctx, page, st = _setup(browser)
    page.evaluate("document.getElementById('feel-go-btn').click();document.getElementById('feel-go-btn').click()")
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    assert len(st["dreams"]) == 1
    ctx.close()


def test_lost_response_is_rechecked_and_not_duplicated(browser):
    ctx, page, st = _setup(browser)
    st["lose_response"] = 1                     # server saves, response never arrives
    _go(page)
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=20000)
    assert len(st["dreams"]) == 1, "retry must replay, not create a second dream"
    assert st["replays"] == 1
    assert len(st["bodies"]) == 2 and len({b["request_id"] for b in st["bodies"]}) == 1
    ctx.close()


def test_uncertain_state_shows_checking_copy(browser):
    ctx, page, st = _setup(browser, recover_ms=1500)
    st["lose_response"] = 1
    _go(page)
    page.wait_for_function("document.getElementById('iw-status').textContent.indexOf('may have been saved') > -1", timeout=8000)
    txt = page.locator("#iw-status").inner_text()
    assert "Your dream may have been saved" in txt and "checking before trying again" in txt
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=20000)
    assert len(st["dreams"]) == 1
    ctx.close()


def test_failure_keeps_words_and_emotions_and_retry_reuses_id(browser):
    ctx, page, st = _setup(browser)
    st["fail_once"] = 1                         # clean in-stream provider error, nothing saved
    _go(page)
    page.wait_for_selector("#interp-wait.failed", timeout=10000)
    assert "We couldn’t finish interpreting your dream." in page.locator("#iw-error").inner_text()
    assert "Your words and selected emotions are still here." in page.locator("#iw-status").inner_text()
    assert len(st["dreams"]) == 0
    page.click("#iw-back-btn")
    assert page.locator("#dream-input").input_value() == "A brass key in a hallway."   # words kept
    assert page.locator("#feel-go-btn").is_visible()                                   # choices kept
    _go(page)
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    assert len(st["dreams"]) == 1
    assert len({b["request_id"] for b in st["bodies"]}) == 1
    ctx.close()


def test_changed_choices_start_a_new_submission(browser):
    ctx, page, st = _setup(browser)
    st["fail_once"] = 1
    _go(page)
    page.wait_for_selector("#interp-wait.failed", timeout=10000)
    page.click("#iw-back-btn")
    pick_child(page, "sad", 0, 0)               # change the feelings -> different payload
    _go(page)
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    assert len({b["request_id"] for b in st["bodies"]}) == 2
    assert len(st["dreams"]) == 1
    ctx.close()


def test_server_busy_is_polled_not_failed(browser):
    ctx, page, st = _setup(browser, timeout_ms=500)
    st["hang_ms"] = 2000
    _go(page)
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=25000)
    assert st["in_progress_hits"] >= 1 and len(st["dreams"]) == 1
    ctx.close()


def test_pre_create_network_failure_then_retry_succeeds_once(browser):
    ctx, page, st = _setup(browser)
    st["abort"] = True                          # never reaches the server
    _go(page)
    page.wait_for_function("document.getElementById('iw-status').textContent.indexOf('may have been saved') > -1", timeout=8000)
    st["abort"] = False
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=20000)
    assert len(st["dreams"]) == 1 and len({b["request_id"] for b in st["bodies"]}) == 1
    ctx.close()


def test_older_backend_never_gets_an_automatic_resend(browser):
    ctx, page, st = _setup(browser)
    st["old_backend"] = True                    # /health lacks idempotent_interpret
    st["lose_response"] = 1
    _go(page)
    page.wait_for_selector("#interp-wait.failed", timeout=10000)
    assert "Check your Journal before trying again" in page.locator("#iw-error").inner_text()
    page.wait_for_timeout(800)
    assert len(st["bodies"]) == 1 and len(st["dreams"]) == 1
    ctx.close()


VIEWPORTS = [(320, 568), (375, 667), (390, 600), (390, 844), (430, 932), (1280, 800)]


@pytest.mark.parametrize("w,h", VIEWPORTS)
def test_recoverable_error_screen_fits_every_viewport(browser, w, h):
    ctx, page, st = make(browser, width=w, height=h)
    to_explorer(page, "A brass key in a hallway.")
    pick_child(page, "fear", 0, 0)
    st["fail_once"] = 1
    _go(page)
    page.wait_for_selector("#interp-wait.failed", timeout=10000)
    page.wait_for_timeout(400)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    for sel in ("#iw-error", "#iw-status", "#iw-retry-btn", "#iw-back-btn"):
        box = page.locator(sel).bounding_box()
        assert box and box["x"] >= -1 and box["x"] + box["width"] <= w + 1, (sel, box)
        assert box["y"] >= 0 and box["y"] + box["height"] <= h + 1, (sel, box, "must be reachable without scrolling")
    assert page.locator("#iw-retry-btn").bounding_box()["height"] >= 40
    ctx.close()


@pytest.mark.parametrize("w,h", VIEWPORTS)
def test_checking_screen_fits_every_viewport(browser, w, h):
    ctx, page, st = make(browser, width=w, height=h, recover_ms=4000)
    to_explorer(page, "A brass key in a hallway.")
    pick_child(page, "fear", 0, 0)
    st["lose_response"] = 1
    _go(page)
    page.wait_for_function("document.getElementById('iw-status').textContent.indexOf('may have been saved') > -1", timeout=8000)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    box = page.locator("#iw-status").bounding_box()
    assert box["x"] >= -1 and box["x"] + box["width"] <= w + 1 and box["y"] + box["height"] <= h
    ctx.close()


def test_reduced_motion_recovery_still_works(browser):
    ctx, page, st = _setup(browser, reduced=True)
    st["lose_response"] = 1
    _go(page)
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=20000)
    assert len(st["dreams"]) == 1
    ctx.close()


def test_keyboard_can_retry_from_error_screen(browser):
    ctx, page, st = _setup(browser)
    st["fail_once"] = 1
    _go(page)
    page.wait_for_selector("#interp-wait.failed", timeout=10000)
    page.focus("#iw-retry-btn")
    assert page.evaluate("document.activeElement.id") == "iw-retry-btn"
    page.keyboard.press("Enter")
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    assert len(st["dreams"]) == 1
    ctx.close()
