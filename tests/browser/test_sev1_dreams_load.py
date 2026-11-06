"""SEV-1 -- a failed dreams request must never look like an empty journal."""
import pytest

from tests.browser.harness import make

pytestmark = pytest.mark.browser


def D(i):
    return {"id": i, "timestamp": "2026-10-%02dT10:00:00Z" % (i + 1), "raw_text": "Synthetic dream number %d." % i, "interpretation": "r",
            "symbols": [], "emotions": ["trusting"], "emotions_plutchik": ["Trust"], "people": ["Brother"], "settings": [], "themes": [],
            "symbol_icons": {}, "emotions_reported": [], "conversation": [], "location": ""}


def _journal(page):
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=archive]').click()")
    page.wait_for_timeout(300)
    return page.locator("#archive-list").inner_text()


@pytest.mark.parametrize("beh", ["500", "abort"])
def test_failed_load_shows_error_and_retry_not_empty_journal(browser, beh):
    ctx, page, st = make(browser, dreams=[D(1), D(2), D(3)], dreams_script=[beh])
    page.wait_for_selector("#dreams-load-banner:not([hidden])", state="attached", timeout=6000)
    txt = _journal(page)
    assert "Nothing logged yet" not in txt
    assert "couldn't be loaded" in txt
    assert "safe" in txt                                                        # Stage 27a: the Journal card carries the message
    assert "boom" not in page.locator("body").inner_text()
    retry = page.locator("#dreams-load-card-retry-btn")      # Stage 27a: Retry lives inside the card
    assert retry.bounding_box()["height"] >= 43
    retry.click()
    page.wait_for_function("document.querySelectorAll('#archive-list .archive-item').length > 0", timeout=8000)
    assert "3 dreams" in page.locator("#archive-count").inner_text()
    assert page.locator("#archive-list .archive-item").count() == 3
    assert st["dreams_calls"] == [beh, "ok"]
    ctx.close()


def test_background_refresh_failure_keeps_loaded_dreams(browser):
    ctx, page, st = make(browser, dreams=[D(1), D(2)])
    assert page.locator("#dreams-load-banner").is_hidden()
    _journal(page)
    assert page.locator("#archive-list .archive-item").count() == 2
    st["dreams_script"] = ["500"]
    page.evaluate("document.getElementById('dreams-load-retry-btn').click()")
    page.wait_for_selector("#dreams-load-banner:not([hidden])", state="attached", timeout=6000)
    assert page.locator("#archive-list .archive-item").count() == 2          # nothing was cleared
    assert "last loaded dreams" in page.locator("#dreams-load-banner-text").text_content()
    assert "Nothing logged yet" not in page.locator("#archive-list").inner_text()
    ctx.close()


def test_genuinely_empty_account_still_shows_the_empty_state(browser):
    ctx, page, st = make(browser, dreams=[])
    txt = _journal(page)
    assert "Nothing logged yet" in txt
    assert page.locator("#dreams-load-banner").is_hidden()
    ctx.close()


def test_refresh_does_not_duplicate_dreams_and_requests_do_not_pile_up(browser):
    ctx, page, st = make(browser, dreams=[D(1), D(2), D(3)])
    page.reload(); page.wait_for_selector("#app-shell:not([hidden])"); page.wait_for_timeout(800)
    assert page.locator("#archive-list .archive-item").count() == 3
    n = len(st["dreams_calls"])
    page.evaluate("document.getElementById('dreams-load-retry-btn').click();document.getElementById('dreams-load-retry-btn').click()")
    page.wait_for_timeout(600)
    assert len(st["dreams_calls"]) - n == 1                                  # concurrent retries share one request
    assert page.locator("#archive-list .archive-item").count() == 3
    ctx.close()
