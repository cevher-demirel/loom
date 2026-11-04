"""Stage 24c -- evidence-based Similar Dreams reasons and Recurring connections on Dream Detail."""
import re

import pytest

from tests.browser.harness import make

pytestmark = pytest.mark.browser


def D(i, ts, text, **kw):
    d = {"id": i, "timestamp": ts, "raw_text": text, "interpretation": "A reading.",
         "symbols": [], "emotions": ["trusting"], "emotions_plutchik": ["Trust"], "people": [], "settings": [], "themes": [],
         "symbol_icons": {}, "emotions_reported": [], "conversation": [], "location": ""}
    d.update(kw)
    return d


def dataset():
    return [
        D(1, "2026-10-26T10:00:00Z", "My brother sat with me.", people=["Brother"]),
        D(2, "2026-10-27T10:00:00Z", "I was in a room with my brother.", people=["my brother"]),
        D(3, "2026-10-31T22:59:00Z", "I came into Barber shop for haircut and my brother owned the shop.", people=["Brother"],
          symbols=["Haircut"], symbol_icons={"Haircut": "scissors"}),
        D(4, "2026-11-02T12:44:00Z", "I saw a red bicycle in a field.", emotions=["joyful"], symbols=["bicycle"], symbol_icons={"bicycle": "bike"}),
        D(5, "2026-11-03T16:04:00Z", "I was in a barber shop with bunch of people. My brother sat on the chair.", people=["Brother"],
          symbols=["Barber chair"], symbol_icons={"Barber chair": "armchair"}),
    ]


def sim(did, text):
    return {"id": did, "timestamp": "2026-11-03T16:04:00Z", "match": 76, "snippet": text[:60], "full": text}


def _open_dream(browser, dream_id, w=390, h=844):
    ds = dataset()
    ctx, page, st = make(browser, width=w, height=h, dreams=ds)
    st["similar"] = {3: [sim(5, ds[4]["raw_text"]), sim(4, ds[3]["raw_text"])], 5: [sim(3, ds[2]["raw_text"])]}
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=archive]').click()")
    page.wait_for_timeout(500)
    page.locator("#archive-list .archive-item, .archive-list .archive-item", has_text=ds[dream_id - 1]["raw_text"][:20]).first.click()
    page.wait_for_selector("#dream-screen:not([hidden])")
    page.wait_for_timeout(600)
    return ctx, page, st


def test_similar_cards_show_supported_reasons_and_no_fake_percentage(browser):
    ctx, page, st = _open_dream(browser, 3)
    cards = page.locator("#dream-screen-similar .similar-card")
    assert cards.count() == 2
    first = cards.nth(0).inner_text()
    assert "Similar meaning" in first and "%" not in first
    assert "Same person: Brother" in first
    assert "Both entries mention: barber shop" in first          # written in both, tagged on neither
    second = cards.nth(1).inner_text()
    assert "Similar overall meaning. No shared tags." not in first
    assert "Same person" not in second and "barber" not in second.lower().split("similar")[0]   # no reason invented for the bicycle dream
    assert st["errors"] == []
    ctx.close()


def test_open_similar_dream_and_come_back_to_the_previous_one(browser):
    ctx, page, st = _open_dream(browser, 3)
    page.locator("#dream-screen-similar .similar-card-open").first.click()
    page.wait_for_timeout(500)
    assert "barber shop with bunch" in page.locator("#dream-screen-text-display, #dream-screen").first.inner_text().lower()
    assert "Previous dream" in page.locator("#dream-screen-back-label").inner_text()
    page.click("#dream-screen-back-btn")
    page.wait_for_timeout(500)
    assert "came into barber shop for haircut" in page.locator("#dream-screen").inner_text().lower()
    page.click("#dream-screen-back-btn")
    page.wait_for_timeout(400)
    assert not page.locator("#dream-screen").is_visible()
    ctx.close()


def test_recurring_connections_lists_supported_items_and_opens_them(browser):
    ctx, page, st = _open_dream(browser, 3)
    sec = page.locator("#dream-screen-recurring")
    txt = sec.inner_text()
    assert "Recurring connections" in txt and "Brother" in txt and "appears in 4 dreams" in txt
    assert "Haircut" not in txt                                   # appears in only one dream: not recurring
    assert "bicycle" not in txt.lower()
    for b in sec.locator("button").all():
        assert b.bounding_box()["height"] >= 43
    sec.locator("[data-recurring-element='person:brother']").click()
    page.wait_for_timeout(500)
    assert page.locator("#symbol-screen").is_visible()
    assert page.locator("#symbol-screen-name").inner_text().strip() == "Brother"
    page.click("#symbol-screen-back-btn")
    page.wait_for_timeout(300)
    assert page.locator("#dream-screen").is_visible()              # returns to the dream
    ctx.close()


def test_recurring_pair_opens_the_connection_preview(browser):
    ctx, page, st = _open_dream(browser, 3)
    pair = page.locator("#dream-screen-recurring [data-recurring-pair]")
    assert pair.count() >= 1
    pair.first.click()
    page.wait_for_timeout(600)
    assert not page.locator("#dream-screen").is_visible()
    assert page.locator("#loom-preview-sheet").is_visible()
    assert re.search(r"Together in \d+ dreams", page.locator("#loom-preview-connection-stat").inner_text())
    ctx.close()


def test_no_recurring_section_for_a_dream_with_nothing_recurring(browser):
    ctx, page, st = _open_dream(browser, 4)
    assert page.locator("#dream-screen-recurring").inner_text().strip() == ""
    ctx.close()
