"""Stage 24f -- the October 31 barber-shop / Brother regression (synthetic data mirroring the owner's screenshots)."""
import pytest

from tests.browser.harness import make

pytestmark = pytest.mark.browser

OCT31_TEXT = ("I came into Barber shop for haircut and my brother owned the shop and he was a barber. "
              "There were two girls in the same room. He was busy cutting their hairs. I had to wait for my turn to come")
NOV3_TEXT = ("I was in a barber shop with bunch of people. This time my brother were sitting on the chair and I was the one "
             "who were supposed to trim his back of neck.")


def D(i, ts, text, **kw):
    d = {"id": i, "timestamp": ts, "raw_text": text, "interpretation": "A reading of this dream.",
         "symbols": [], "emotions": ["trusting"], "emotions_plutchik": ["Trust"], "people": [], "settings": [], "themes": [],
         "symbol_icons": {}, "emotions_reported": [], "conversation": [], "location": "", "confirmed_people": []}
    d.update(kw)
    return d


def dataset():
    return [
        D(1, "2026-10-26T10:00:00Z", "My brother and I sat at a table.", people=["Brother"]),
        D(2, "2026-10-27T10:00:00Z", "I was in a room with my mom and brother.", people=["my brother"]),
        D(3, "2026-10-31T22:59:00Z", OCT31_TEXT, symbols=["Haircut"], symbol_icons={"Haircut": "scissors"}),     # extraction missed Brother
        D(4, "2026-11-02T12:44:00Z", "I saw myself driving a child push car.", symbols=["Electric child push car"], symbol_icons={"Electric child push car": "car"}),
        D(5, "2026-11-03T16:04:00Z", NOV3_TEXT, people=["Brother"], symbols=["Barber chair"], symbol_icons={"Barber chair": "armchair"}),
    ]


def _open_brother(browser, w=390, h=844):
    ctx, page, st = make(browser, width=w, height=h, dreams=dataset())
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=symbols]').click()")
    page.wait_for_timeout(700)
    page.click("#loom-view-list-btn")
    page.wait_for_timeout(300)
    page.locator("#loom-list-view .symbol-lib-item", has_text="Brother").first.click()
    page.wait_for_timeout(500)
    page.click("#symbol-screen-tab-dreams-btn")
    page.wait_for_timeout(300)
    return ctx, page, st


def test_counts_and_labels_distinguish_tagged_from_written(browser):
    ctx, page, st = _open_brother(browser)
    assert "Found in 3 dreams" in page.locator("#symbol-screen-stat").inner_text()        # tagged only: Oct 26, Oct 27, Nov 3
    rel = page.locator("#symbol-screen-related-list .archive-item").all_inner_texts()
    assert len(rel) == 3 and not any("barber shop for haircut" in t for t in rel)
    note = page.locator("#symbol-screen-mention-note").inner_text()
    assert "1 more journal entry without a Brother tag" in note
    mentioned = page.locator("#symbol-screen-mentioned-list .archive-item")
    assert mentioned.count() == 1 and "Oct 31, 2026" in mentioned.first.inner_text()      # clearly identifiable
    assert "Written in these entries, not tagged" in page.locator("#symbol-screen-mentioned-section").inner_text()
    ctx.close()


def test_open_oct31_directly_and_return_to_brother_then_map(browser):
    ctx, page, st = _open_brother(browser)
    page.locator("#symbol-screen-mentioned-list .archive-item").first.click()
    page.wait_for_timeout(500)
    assert page.locator("#dream-screen").is_visible()
    assert "barber shop for haircut" in page.locator("#dream-screen").inner_text().lower()
    page.click("#dream-screen-back-btn")
    page.wait_for_timeout(500)
    assert page.locator("#symbol-screen").is_visible()                                     # back on Brother ...
    assert page.locator("#symbol-screen-tabpanel-dreams").is_visible()                     # ... on the same tab
    page.click("#symbol-screen-back-btn")
    page.wait_for_timeout(400)
    assert page.locator("#loom-list-view").is_visible()            # ... and then the Map
    assert st["errors"] == []
    ctx.close()


def test_confirming_adds_oct31_everywhere_without_touching_anything_else(browser):
    ctx, page, st = _open_brother(browser)
    page.locator("[data-confirm-dream='3']").click()
    page.wait_for_function("document.getElementById('symbol-screen-stat').innerText.indexOf('4 dreams') > -1", timeout=5000)
    assert st["confirm_puts"] == [{"dream_id": 3, "category": "person", "label": "Brother"}]
    assert "Found in 4 dreams" in page.locator("#symbol-screen-stat").inner_text()
    assert not page.locator("#symbol-screen-mention-note").is_visible()
    rel = page.locator("#symbol-screen-related-list")
    assert "Oct 31, 2026" in rel.inner_text() and "Added by you" in rel.inner_text()
    assert rel.locator(".archive-item").count() == 4
    dream_ids = [d["id"] for d in st["dreams"] if d["people"]]
    assert 4 not in dream_ids                                                              # the unrelated dream gained nothing
    # chronological position: Oct 31 sits between Oct 27 and Nov 3
    import re
    dates = [re.search(r"[A-Z][a-z]{2} \d{1,2}, 2026", t).group(0) for t in rel.locator(".archive-item").all_inner_texts()]
    assert dates == ["Nov 3, 2026", "Oct 31, 2026", "Oct 27, 2026", "Oct 26, 2026"]
    # the original dream text is untouched
    assert [d["raw_text"] for d in st["dreams"] if d["id"] == 3] == [OCT31_TEXT]
    # undo works and restores the written-not-tagged state
    page.locator("[data-unconfirm-dream='3']").click()
    page.wait_for_function("document.getElementById('symbol-screen-stat').innerText.indexOf('3 dreams') > -1", timeout=5000)
    assert page.locator("#symbol-screen-mention-note").is_visible()
    # Map relationship counts follow the confirmation too
    page.locator("[data-confirm-dream='3']").click()
    page.wait_for_function("document.getElementById('symbol-screen-stat').innerText.indexOf('4 dreams') > -1", timeout=5000)
    page.click("#symbol-screen-back-btn")
    page.wait_for_timeout(400)
    page.locator("#loom-list-view .symbol-lib-item", has_text="Brother").first.inner_text()
    assert "4" in page.locator("#loom-list-view .symbol-lib-item", has_text="Brother").first.inner_text()
    assert st["errors"] == []
    ctx.close()


def test_a_failed_save_keeps_state_and_is_announced(browser):
    ctx, page, st = _open_brother(browser)
    page.route("**/entity-confirmations", lambda route: route.fulfill(status=500, content_type="application/json", body="{}"))
    page.locator("[data-confirm-dream='3']").click()
    page.wait_for_timeout(600)
    assert "Couldn’t save that" in page.locator("#symbol-screen-mention-status").inner_text()
    assert "Found in 3 dreams" in page.locator("#symbol-screen-stat").inner_text()
    assert page.locator("[data-confirm-dream='3']").is_enabled()
    ctx.close()
