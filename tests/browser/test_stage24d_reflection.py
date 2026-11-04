"""Stage 24d -- element reflection states: success, failure, retry, stall, revisit, no duplicate requests."""
import pytest

from tests.browser.harness import make

pytestmark = pytest.mark.browser


def D(i):
    return {"id": i, "timestamp": "2026-10-%02dT10:00:00Z" % (i + 1), "raw_text": "My brother, dream %d." % i, "interpretation": "r",
            "symbols": [], "emotions": ["trusting"], "emotions_plutchik": ["Trust"], "people": ["Brother"], "settings": [], "themes": [],
            "symbol_icons": {}, "emotions_reported": [], "conversation": [], "location": ""}


def _open(browser, script, stall_ms=None, w=390, h=844):
    ctx, page, st = make(browser, width=w, height=h, dreams=[D(1), D(2), D(3)])
    st["insight_script"] = list(script)
    if stall_ms:
        page.add_init_script("window.__LOOM_REFLECTION_STALL_MS=%d;" % stall_ms)
        page.reload()
        page.wait_for_selector("#app-shell:not([hidden])")
        page.wait_for_timeout(700)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=symbols]').click()")
    page.wait_for_timeout(600)
    page.click("#loom-view-list-btn")
    page.wait_for_timeout(300)
    page.locator("#loom-list-view .symbol-lib-item", has_text="Brother").first.click()
    return ctx, page, st


def _text(page, sel):
    return page.locator(sel).inner_text().strip()


def test_success_renders_sections_and_revisit_makes_no_second_call(browser):
    ctx, page, st = _open(browser, ["ok"])
    page.wait_for_function("document.getElementById('symbol-screen-general').innerText.length > 0", timeout=5000)
    assert "General reading text." in _text(page, "#symbol-screen-general")
    assert "Journal reading text." in _text(page, "#symbol-screen-journal")
    assert not page.locator("#symbol-screen-reflection-status").is_visible()
    assert not page.locator("#symbol-screen-reflection-error").is_visible()
    page.click("#symbol-screen-back-btn")
    page.wait_for_timeout(300)
    page.locator("#loom-list-view .symbol-lib-item", has_text="Brother").first.click()
    page.wait_for_timeout(500)
    assert "General reading text." in _text(page, "#symbol-screen-general")
    assert st["insight_calls"] == ["insight/stream"]                      # cached: no repeated AI call
    ctx.close()


def test_failure_is_recoverable_sanitised_keeps_journal_facts_and_retry_works(browser):
    ctx, page, st = _open(browser, ["meta_error", "http500", "ok"])
    page.wait_for_selector("#symbol-screen-reflection-error:not([hidden])", timeout=6000)
    body = page.locator("#symbol-screen").inner_text()
    assert "Couldn't put together a reflection" in body
    assert "Malformed" not in body and "raw provider detail" not in body and "boom" not in body   # nothing internal is shown
    assert st["insight_calls"] == ["insight/stream", "insight"]           # one bounded fallback, then it stops
    assert not page.locator("#symbol-screen-general").is_visible()        # no empty "Possible meanings" heading above the error
    assert page.locator("#symbol-screen-journal-shows-section").is_visible()   # the journal facts stay
    retry = page.locator("#symbol-screen-reflection-retry-btn")
    assert retry.bounding_box()["height"] >= 43
    retry.click()
    page.wait_for_function("document.getElementById('symbol-screen-general').innerText.length > 0", timeout=5000)
    assert not page.locator("#symbol-screen-reflection-error").is_visible()
    assert "General reading text." in _text(page, "#symbol-screen-general")
    assert st["insight_calls"][-1] == "insight/stream"
    assert st["errors"] == []
    ctx.close()


def test_stalled_request_ends_with_a_retry_instead_of_loading_forever(browser):
    ctx, page, st = _open(browser, ["hang", "ok"], stall_ms=1500)
    assert page.locator("#symbol-screen-reflection-status").is_visible()      # honest loading state first
    page.wait_for_selector("#symbol-screen-reflection-error:not([hidden])", timeout=6000)
    assert "taking longer than expected" in _text(page, "#symbol-screen-reflection-error-text")
    assert not page.locator("#symbol-screen-reflection-status").is_visible()
    page.click("#symbol-screen-reflection-retry-btn")
    page.wait_for_function("document.getElementById('symbol-screen-general').innerText.length > 0", timeout=5000)
    assert len(st["insight_calls"]) == 2
    ctx.close()


def test_double_tap_on_retry_sends_one_request(browser):
    ctx, page, st = _open(browser, ["hang", "ok", "ok"], stall_ms=1200)
    page.wait_for_selector("#symbol-screen-reflection-error:not([hidden])", timeout=6000)
    retry = page.locator("#symbol-screen-reflection-retry-btn")
    retry.dblclick()
    page.wait_for_function("document.getElementById('symbol-screen-general').innerText.length > 0", timeout=5000)
    page.wait_for_timeout(500)
    assert len(st["insight_calls"]) == 2
    ctx.close()


def test_leaving_while_loading_then_returning_shows_only_the_new_result(browser):
    ctx, page, st = _open(browser, ["hang", "ok"], stall_ms=30000)
    page.wait_for_timeout(400)
    page.click("#symbol-screen-back-btn")
    page.wait_for_timeout(300)
    page.locator("#loom-list-view .symbol-lib-item", has_text="Brother").first.click()
    page.wait_for_function("document.getElementById('symbol-screen-general').innerText.length > 0", timeout=5000)
    assert not page.locator("#symbol-screen-reflection-error").is_visible()
    assert "General reading text." in _text(page, "#symbol-screen-general")
    ctx.close()
