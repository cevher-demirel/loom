"""Stage 25 -- Journal loading/error/empty/retry at phone widths, and the Map/element screens after a reload."""
import pytest

from tests.browser.harness import make
from tests.browser.test_stage24c_relationships import dataset

pytestmark = pytest.mark.browser
WIDTHS = [(320, 568), (375, 667), (390, 844), (430, 932)]


def _journal(page):
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=archive]').click()")
    page.wait_for_timeout(300)


@pytest.mark.parametrize("w,h", WIDTHS)
def test_error_state_and_retry_fit_phone_widths(browser, w, h):
    ds = dataset()
    ctx, page, st = make(browser, width=w, height=h, dreams=ds, dreams_script=["500"])
    page.wait_for_selector("#dreams-load-banner:not([hidden])", timeout=6000)
    _journal(page)
    assert "Nothing logged yet" not in page.locator("#archive-list").inner_text()
    assert page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0
    box = page.locator("#dreams-load-retry-btn").bounding_box()
    assert box["height"] >= 43 and box["x"] >= 0 and box["x"] + box["width"] <= w
    page.click("#dreams-load-retry-btn")
    page.wait_for_function("document.querySelectorAll('#archive-list .archive-item').length > 0", timeout=8000)
    assert page.locator("#archive-list .archive-item").count() == len(ds)      # recovered, no duplicates
    assert st["errors"] == []
    ctx.close()


def test_map_and_element_screen_work_after_recovery(browser):
    ctx, page, st = make(browser, dreams=dataset(), dreams_script=["500"])
    page.wait_for_selector("#dreams-load-banner:not([hidden])", timeout=6000)
    page.click("#dreams-load-retry-btn")
    page.wait_for_function("document.querySelectorAll('#archive-list .archive-item').length > 0", timeout=8000)
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=symbols]').click()")
    page.wait_for_timeout(600)
    page.click("#loom-view-list-btn")
    page.locator("#loom-list-view .symbol-lib-item", has_text="Brother").first.click()
    page.wait_for_selector("#symbol-screen:not([hidden])")
    page.wait_for_timeout(500)
    assert "Brother" in page.locator("#symbol-screen-name").inner_text()
    assert page.locator("#symbol-screen-related-list .archive-item").count() >= 4
    ctx.close()


def test_failure_on_a_second_load_keeps_earlier_data_everywhere(browser):
    ctx, page, st = make(browser, dreams=dataset())
    st["dreams_script"] = ["abort"]
    page.evaluate("document.getElementById('dreams-load-retry-btn').click()")
    page.wait_for_selector("#dreams-load-banner:not([hidden])", timeout=6000)
    _journal(page)
    assert page.locator("#archive-list .archive-item").count() == len(dataset())
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=symbols]').click()")
    page.wait_for_timeout(500)
    assert page.locator('.loom-graph-node--symbol[data-cat-key="person:brother"]').count() == 1
    ctx.close()
