"""Stage 24e -- consistent emotion wording and layout/tap-target sweep across viewports."""
import pytest

from tests.browser.harness import make
from tests.browser.test_stage24c_relationships import dataset, sim

pytestmark = pytest.mark.browser

VIEWPORTS = [(320, 568), (375, 667), (390, 844), (430, 932), (768, 1024), (1280, 800), (844, 390)]


def _open(browser, idx, w, h, plutchik=None):
    ds = dataset()
    if plutchik:
        ds[idx - 1]["emotions_plutchik"] = plutchik
    ctx, page, st = make(browser, width=w, height=h, dreams=ds)
    st["similar"] = {3: [sim(5, ds[4]["raw_text"]), sim(4, ds[3]["raw_text"])]}
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=archive]').click()")
    page.wait_for_timeout(400)
    page.locator("#archive-list .archive-item, .archive-list .archive-item", has_text=ds[idx - 1]["raw_text"][:20]).first.click()
    page.wait_for_selector("#dream-screen:not([hidden])")
    page.wait_for_timeout(600)
    return ctx, page, st


def test_emotion_wheel_uses_the_same_name_as_the_rest_of_the_app(browser):
    ctx, page, st = _open(browser, 4, 390, 844, plutchik=["Joy"])
    txt = page.locator("#dream-screen").inner_text()
    assert "Happy" in txt
    assert "Joy" not in txt
    ctx.close()


@pytest.mark.parametrize("w,h", VIEWPORTS)
def test_dream_detail_has_no_horizontal_overflow_and_tappable_controls(browser, w, h):
    ctx, page, st = _open(browser, 3, w, h)
    over = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 0, over
    scr = page.evaluate("(function(){var s=document.getElementById('dream-screen');return s.scrollWidth-s.clientWidth})()")
    assert scr <= 1, scr
    for sel in ["#dream-screen-recurring button", "#dream-screen-similar .similar-card-open", "#dream-screen-similar .similar-card-toggle"]:
        for b in page.locator(sel).all():
            if b.is_visible():
                assert b.bounding_box()["height"] >= 43, (sel, w)
    assert st["errors"] == []
    ctx.close()


@pytest.mark.parametrize("w,h", VIEWPORTS)
def test_element_screen_fits_the_viewport(browser, w, h):
    ctx, page, st = _open(browser, 3, w, h)
    page.locator("#dream-screen-recurring [data-recurring-element='person:brother']").click()
    page.wait_for_selector("#symbol-screen:not([hidden])")
    page.wait_for_timeout(500)
    assert page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0
    assert page.evaluate("(function(){var s=document.getElementById('symbol-screen');return s.scrollWidth-s.clientWidth})()") <= 1
    back = page.locator("#symbol-screen-back-btn").bounding_box()
    assert back["height"] >= 43 and back["width"] >= 43
    ctx.close()
