"""Stage 23e -- naming, copy and excerpt consistency."""
import pytest

from tests.browser.harness import make, to_explorer, pick_child
from tests.browser.seed import dreams

pytestmark = pytest.mark.browser


def _ready(browser, n=30, w=390, h=844):
    ctx, page, st = make(browser, width=w, height=h, dreams=dreams(n))
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.wait_for_timeout(400)
    return ctx, page, st


def _tab(page, t):
    page.evaluate("(t)=>document.querySelector('.bottom-tab-btn[data-tab=\"'+t+'\"]').click()", t)
    page.wait_for_timeout(700)


def test_dream_detail_back_says_journal_from_journal_and_after_submit(browser):
    ctx, page, st = _ready(browser)
    _tab(page, "archive")
    page.locator("#panel-archive .archive-item").first.click()
    page.wait_for_timeout(500)
    assert page.inner_text("#dream-screen-back-label") == "Journal"
    page.click("#dream-screen-back-btn")
    assert "Archive" not in page.inner_text("body").replace("Archive.", "")
    ctx.close()


@pytest.mark.parametrize("w", [320, 375, 390, 430])
def test_journal_search_placeholder_is_not_clipped(browser, w):
    ctx, page, st = _ready(browser, w=w, h=800)
    _tab(page, "archive")
    ph = page.get_attribute("#archive-search-input", "placeholder")
    assert ph == "Search your journal"
    fits = page.evaluate("""() => { const i = document.getElementById('archive-search-input'); const c = document.createElement('canvas').getContext('2d');
        const cs = getComputedStyle(i); c.font = cs.fontSize + ' ' + cs.fontFamily;
        return c.measureText(i.placeholder).width <= i.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight); }""")
    assert fits
    ctx.close()


def test_journal_has_one_obvious_record_action_and_it_works(browser):
    ctx, page, st = _ready(browser)
    _tab(page, "archive")
    assert not page.locator("#journal-head-add-btn").is_visible()
    btn = page.locator("#journal-record-btn")
    assert btn.is_visible() and btn.inner_text().strip() == "Record a dream"
    btn.click()
    page.wait_for_timeout(500)
    assert page.locator("#dream-input").is_visible()
    ctx.close()


def test_timeline_subtabs_do_not_repeat_the_word_timeline(browser):
    ctx, page, st = _ready(browser)
    _tab(page, "symbols")
    page.click("#loom-view-timeline-btn")
    page.wait_for_timeout(300)
    page.locator("#loom-timeline-picker-list button, #loom-timeline-picker-list .archive-item").first.click()
    page.wait_for_timeout(500)
    labels = [t.strip() for t in page.locator(".loom-timeline-sub-toggle button").all_inner_texts()]
    assert labels == ["By date", "By month", "Patterns"]
    for sel, panel in (("#loom-timeline-sub-month-btn", "#loom-timeline-sub-month"), ("#loom-timeline-sub-patterns-btn", "#loom-timeline-sub-patterns"), ("#loom-timeline-sub-timeline-btn", "#loom-timeline-sub-timeline")):
        page.click(sel)
        page.wait_for_timeout(250)
        assert page.locator(panel).is_visible()
    ctx.close()


def test_long_excerpts_end_on_a_word_with_ellipsis_and_still_open_the_dream(browser):
    long_text = "I walked through the long marble corridor of an unfamiliar museum while somebody whispered my name from behind every statue and the lights kept changing colour until I woke"
    ds = dreams(5)
    ds[0]["raw_text"] = long_text
    ctx, page, st = make(browser, width=390, height=844, dreams=ds)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.wait_for_timeout(400)
    _tab(page, "archive")
    sn = page.locator("#panel-archive .archive-snippet", has_text="marble corridor").first
    txt = sn.inner_text()
    assert txt.endswith("…") and not txt.endswith(" …")
    assert long_text.startswith(txt[:-1])
    assert long_text[len(txt) - 1] == " "                      # cut on a word boundary
    sn.click()
    page.wait_for_timeout(500)
    assert long_text in page.inner_text("#dream-screen")      # full dream still opens
    ctx.close()


def test_settings_rows_describe_profile_vs_account(browser):
    ctx, page, st = _ready(browser)
    page.evaluate("document.querySelector('.header-gear-btn, #home-link-settings').click()")
    page.wait_for_timeout(700)
    assert "Photo" in page.inner_text("#settings-go-profile-btn")
    t = page.inner_text("#settings-go-account-btn")
    assert "About you" in t and "delete" in t
    page.click("#settings-go-account-btn")
    page.wait_for_timeout(400)
    assert page.locator("#profile-name").is_visible() and page.locator("#delete-account-password").count() == 1
    ctx.close()


def test_no_user_facing_archive_wording_left(browser):
    ctx, page, st = _ready(browser)
    for t in ("home", "archive", "symbols", "patterns"):
        _tab(page, t)
        assert "archive" not in page.inner_text("body").lower(), t
    ctx.close()
