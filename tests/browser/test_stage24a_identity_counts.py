"""Stage 24a -- aliases, distinct-dream counts and tagged-vs-mentioned (real browser behaviour)."""
import pytest

from tests.browser.harness import make

pytestmark = pytest.mark.browser


def D(i, text, **kw):
    d = {"id": i, "timestamp": "2026-10-%02dT10:00:00Z" % (i + 1), "raw_text": text, "interpretation": "A reading.",
         "symbols": [], "emotions": ["calm"], "emotions_plutchik": ["Trust"], "people": [], "settings": [], "themes": [],
         "symbol_icons": {}, "emotions_reported": [], "conversation": [], "location": ""}
    d.update(kw)
    return d


def _open_element(browser, dreams, label, w=390, h=844):
    ctx, page, st = make(browser, width=w, height=h, dreams=dreams)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=symbols]').click()")
    page.wait_for_timeout(700)
    page.click("#loom-view-list-btn")
    page.wait_for_timeout(300)
    page.locator("#loom-list-view .symbol-lib-item", has_text=label).first.click()
    page.wait_for_timeout(500)
    return ctx, page, st


FATHER_SET = [
    D(1, "My dad drove the car.", people=["my dad"]),
    D(2, "Father was in the kitchen.", people=["Father"]),
    D(3, "I saw my dad in my dream he was happy."),                      # text only, never tagged
    D(4, "A father figure gave advice.", people=["Mentor"]),            # excluded phrase
    D(5, "Dad and daddy both. Dad again.", people=["Dad", "Daddy", "father"]),  # many aliases, ONE dream
    D(6, "My brother-in-law waved. Nothing about the old man."),
]


def test_dad_and_father_are_one_concept_counted_once_per_dream(browser):
    ctx, page, st = _open_element(browser, FATHER_SET, "Father")
    assert page.locator("#symbol-screen-name").inner_text().strip() == "Father"
    assert "Found in 3 dreams" in page.locator("#symbol-screen-stat").inner_text()
    assert page.locator("#symbol-screen-tab-dreams-count").inner_text().strip() == "(3)"
    assert st["errors"] == []
    ctx.close()


def test_text_only_mentions_are_shown_separately_never_counted(browser):
    ctx, page, st = _open_element(browser, FATHER_SET, "Father")
    note = page.locator("#symbol-screen-mention-note")
    assert note.is_visible()
    assert "1 more journal entry without a Father tag" in note.inner_text()   # dream 3 only; 'father figure' excluded
    assert note.bounding_box()["height"] >= 43
    note.click()
    page.wait_for_timeout(300)
    assert page.locator("#symbol-screen-mentioned-list .archive-item").count() == 1
    assert "dad in my dream" in page.locator("#symbol-screen-mentioned-list").inner_text()
    assert page.locator("#symbol-screen-related-list .archive-item").count() == 3   # tagged list unchanged
    ctx.close()


def test_no_mention_note_when_everything_is_tagged(browser):
    ds = [D(1, "My brother called.", people=["my brother"]), D(2, "Brother again.", people=["Brother"])]
    ctx, page, st = _open_element(browser, ds, "Brother")
    assert not page.locator("#symbol-screen-mention-note").is_visible()
    assert not page.locator("#symbol-screen-mentioned-section").is_visible()
    ctx.close()


def test_brother_and_father_stay_separate(browser):
    ds = [D(1, "Brother and Dad.", people=["Brother", "Dad"]), D(2, "Brother.", people=["Brother"])]
    ctx, page, st = _open_element(browser, ds, "Brother")
    assert "Found in 2 dreams" in page.locator("#symbol-screen-stat").inner_text()
    ctx.close()


def test_barbershop_spellings_merge_but_barber_chair_stays_separate(browser):
    ds = [D(1, "x", settings=["barber shop"]), D(2, "y", settings=["Barbershop"]), D(3, "z", settings=["the barber-shop"]),
          D(4, "w", symbols=["barber chair"], symbol_icons={"barber chair": "armchair"})]
    ctx, page, st = _open_element(browser, ds, "Barber shop")
    assert "Found in 3 dreams" in page.locator("#symbol-screen-stat").inner_text()
    ctx.close()
    ctx, page, st = _open_element(browser, ds, "Barber chair")
    assert "Found in 1 dream" in page.locator("#symbol-screen-stat").inner_text()
    ctx.close()


def test_hair_cutting_merges_into_haircut(browser):
    ds = [D(1, "a", symbols=["haircut"], symbol_icons={"haircut": "scissors"}),
          D(2, "b", symbols=["hair cutting"], symbol_icons={"hair cutting": "scissors"})]
    ctx, page, st = _open_element(browser, ds, "Haircut")
    assert "Found in 2 dreams" in page.locator("#symbol-screen-stat").inner_text()
    ctx.close()
