"""Stage 20 browser tests: scroll/dock layout, collapsible tray, wheel resize,
submission reliability and a regression smoke of the other tabs.

Mocked backend only. Real-backend verification is NOT covered here.
"""
import pytest

from harness import make, to_explorer, focus, pick_child, sel_count, settle

VIEWPORTS = [(320, 568), (375, 667), (390, 600), (390, 844), (430, 932)]


def metrics(page):
    return page.evaluate("""() => {
      const r = (s) => { const e = document.querySelector(s); return e ? e.getBoundingClientRect() : null; };
      const sc = document.getElementById('feel-scroll'), nav = r('#bottom-tabs-nav'), dock = r('.feel-dock'), go = r('#feel-go-btn');
      const at = (x, y) => document.elementFromPoint(x, y);
      const navEl = at(nav.left + nav.width / 2, nav.top + nav.height / 2);
      return { sc: sc.getBoundingClientRect().toJSON(), scrollTop: sc.scrollTop, scrollH: sc.scrollHeight, clientH: sc.clientHeight,
               nav: nav.toJSON(), dock: dock && dock.toJSON(), go: go && go.toJSON(),
               navFree: !!navEl && navEl.closest('#bottom-tabs-nav') !== null,
               goFree: go ? at(go.left + go.width / 2, go.top + go.height / 2).closest('#feel-go-btn') !== null : null,
               overflowX: document.documentElement.scrollWidth > innerWidth, outerScroll: document.documentElement.scrollHeight > innerHeight + 1, ih: innerHeight };
    }""")


@pytest.mark.parametrize("w,h", VIEWPORTS)
def test_last_group_last_child_fully_visible_and_dock_clear(browser, w, h):
    ctx, page, _ = make(browser, w, h)
    to_explorer(page)
    pick_child(page, "trust", 0, 0)                      # some selection so the tray + dock are showing
    pick_child(page, "sad", 0, 0)
    focus(page, "fear")
    last_mid = page.locator("[data-feel-mid]").last
    last_mid.click()                                     # expand the final parent group
    last_child = page.locator(".feel-mid").last.locator(".feel-leaf").last
    last_child.click()                                   # real click: Playwright scrolls and fails if anything covers it
    assert page.locator(".feel-mid").last.locator(".feel-leaf.selected").count() == 1
    sc = page.evaluate("(()=>{const s=document.getElementById('feel-scroll');s.scrollTop=s.scrollHeight;return 1})()")
    m = metrics(page)
    box = last_child.bounding_box()
    assert box["y"] >= m["sc"]["top"] - 1 and box["y"] + box["height"] <= m["sc"]["bottom"] + 1   # fully inside the scroll region
    assert m["sc"]["bottom"] <= m["dock"]["top"] + 1 and m["dock"]["bottom"] <= m["nav"]["top"] + 1  # region < dock < nav, no overlap
    assert m["goFree"] and m["navFree"]
    assert not m["overflowX"] and not m["outerScroll"]                                                 # one scroller only
    ctx.close()


@pytest.mark.parametrize("w,h", VIEWPORTS)
def test_no_scroll_trap_wheel_scrolls_region_both_ways(browser, w, h):
    ctx, page, _ = make(browser, w, h)
    to_explorer(page)
    focus(page, "happy")
    for i in range(page.locator("[data-feel-mid]").count()):
        page.locator("[data-feel-mid]").nth(i).click()
    page.evaluate("document.getElementById('feel-scroll').scrollTop = 0")
    m = metrics(page)
    assert m["scrollH"] > m["clientH"]
    page.mouse.move(w / 2, m["sc"]["top"] + 40)
    page.mouse.wheel(0, 600)
    page.wait_for_timeout(150)
    down = page.evaluate("document.getElementById('feel-scroll').scrollTop")
    page.mouse.wheel(0, -2000)
    page.wait_for_timeout(150)
    assert down > 0 and page.evaluate("document.getElementById('feel-scroll').scrollTop") == 0
    ctx.close()


def test_tray_collapse_expand_preserve_selection_and_state(browser):
    ctx, page, _ = make(browser)
    to_explorer(page)
    assert page.locator(".feel-tray").count() == 0                              # nothing selected: no empty card
    pick_child(page, "fear", 0, 0)
    assert "1 emotion selected" in page.locator(".feel-tray").inner_text()
    assert page.locator("[data-feel-tray]").count() == 0                        # single selection needs no toggle
    pick_child(page, "trust", 0, 0)
    tog = page.locator(".feel-tray-toggle")
    assert "Selected Emotions (2)" in tog.inner_text() and tog.get_attribute("aria-expanded") == "false"
    assert page.locator(".feel-more").inner_text() == "+1 more" and page.locator(".feel-clear").count() == 0
    tog.click()
    assert tog.get_attribute("aria-expanded") == "true"
    texts = page.locator(".feel-chip").all_inner_texts()
    assert len(texts) == 2 and any("Fear → Cautious → Timid" in x for x in texts) and any("Trust" in x for x in texts)
    assert sel_count(page) == 2 and page.locator(".feel-clear").count() == 1
    tog.click()
    assert sel_count(page) == 2                                                  # collapsing never drops selections
    page.locator(".feel-more").click()                                           # "+N more" also expands
    assert page.locator(".feel-chip").count() == 2
    ctx.close()


def test_many_selections_keep_tray_bounded_and_action_visible(browser):
    ctx, page, _ = make(browser, 390, 600)
    to_explorer(page)
    n = 0
    for fam in ("fear", "trust", "sad", "happy", "anticipation", "surprise"):
        for mid in (0, 1):
            pick_child(page, fam, mid, 0)
            n += 1
    assert sel_count(page) == n
    page.click("[data-feel-tray]")
    m = metrics(page)
    assert m["dock"]["height"] <= 0.45 * m["ih"]
    assert m["goFree"] and m["dock"]["bottom"] <= m["nav"]["top"] + 1 and m["sc"]["height"] >= 150
    assert page.locator(".feel-chip").count() == n                              # nothing hidden permanently
    page.locator(".feel-chip button").nth(n - 1).click()                         # a chip inside the bounded area is removable
    assert sel_count(page) == n - 1
    ctx.close()


def test_wheel_node_persists_and_resizes_with_transition(browser):
    ctx, page, _ = make(browser)
    to_explorer(page)
    page.evaluate("window.__wrap = document.getElementById('feel-wheelwrap'); window.__w0 = __wrap.getBoundingClientRect().width")
    focus(page, "fear")
    assert page.evaluate("document.getElementById('feel-wheelwrap') === window.__wrap")
    page.wait_for_timeout(400)
    w1 = page.evaluate("__wrap.getBoundingClientRect().width")
    assert page.evaluate("__w0") > w1 >= 200
    assert page.evaluate("getComputedStyle(__wrap).transitionDuration") != "0s"
    ctx.close()
    ctx, page, _ = make(browser, reduced=True)
    to_explorer(page)
    assert page.evaluate("getComputedStyle(document.getElementById('feel-wheelwrap')).transitionDuration") == "0s"
    ctx.close()


def test_scroll_position_and_keyboard_focus_survive_selection(browser):
    ctx, page, _ = make(browser, 390, 600)
    to_explorer(page)
    focus(page, "fear")
    page.locator("[data-feel-mid]").nth(3).click()
    settle(page)
    page.evaluate("document.getElementById('feel-scroll').scrollTop = 220")
    target = page.locator(".feel-mid").nth(3).locator(".feel-check")
    target.focus()
    before = page.evaluate("document.getElementById('feel-scroll').scrollTop")
    page.keyboard.press("Space")
    assert target.get_attribute("aria-checked") == "true"
    assert abs(page.evaluate("document.getElementById('feel-scroll').scrollTop") - before) <= 2
    assert page.evaluate("document.activeElement.getAttribute('data-feel-toggle')") == "fear.anxious"
    ctx.close()


def test_expander_and_child_never_toggle_parent_checkbox(browser):
    ctx, page, _ = make(browser)
    to_explorer(page)
    focus(page, "trust")
    mid = page.locator(".feel-mid").first
    mid.locator("[data-feel-mid]").click()
    assert mid.locator(".feel-check").get_attribute("aria-checked") == "false"
    mid.locator(".feel-leaf").first.click()
    assert mid.locator(".feel-check").get_attribute("aria-checked") == "false"
    mid.locator("[data-feel-mid]").click()                                        # collapse keeps the child selected
    assert page.locator(".feel-chip").count() == 1
    ctx.close()


def test_long_dream_text_submits_unchanged(browser):
    ctx, page, st = make(browser)
    long = ("A very long dream. " * 300).strip()
    to_explorer(page, long)
    pick_child(page, "fear", 0, 0)
    page.click("#feel-go-btn")
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    assert st["bodies"][0]["raw_text"] == long
    ctx.close()


def test_network_interruption_keeps_draft_and_selection_then_retry_succeeds_once(browser):
    ctx, page, st = make(browser)
    st["abort"] = True
    to_explorer(page, "network dream")
    pick_child(page, "fear", 0, 0)
    pick_child(page, "trust", 0, 0)
    page.click("#feel-go-btn")
    page.wait_for_selector("#interp-wait.failed", timeout=10000)
    assert page.locator("#iw-error").inner_text().strip() != ""
    page.click("#iw-back-btn")
    assert sel_count(page) == 2 and page.input_value("#dream-input") == "network dream"
    st["abort"] = False
    page.click("#feel-go-btn")
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    assert len(st["dreams"]) == 1 and st["bodies"][0] == st["bodies"][1]
    ctx.close()


def test_backend_timeout_does_not_strand_the_user(browser):
    ctx, page, st = make(browser, timeout_ms=600)
    st["hang_ms"] = 2500
    to_explorer(page, "slow dream")
    pick_child(page, "sad", 0, 0)
    page.click("#feel-go-btn")
    page.wait_for_selector("#interp-wait.failed", timeout=10000)
    assert "longer than expected" in page.locator("#iw-error").inner_text()
    st["hang_ms"] = 0
    page.click("#iw-retry-btn")
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    assert len(st["dreams"]) == 1 and st["bodies"][-1]["emotions_reported"][0] == "Sadness"
    page.unroute_all(behavior="ignoreErrors")
    ctx.close()


def test_dream_detail_shows_the_submitted_dream(browser):
    ctx, page, st = make(browser)
    to_explorer(page, "A brass key in a hallway.")
    pick_child(page, "fear", 0, 0)
    page.click("#feel-go-btn")
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    body = page.locator("#dream-screen").inner_text()
    assert "brass key" in body and "reading of your dream" in body
    ctx.close()


def _dream(i):
    return {"id": i, "timestamp": "2025-10-%02dT08:00:00Z" % (10 + i), "raw_text": "Dream number %d about a key and water." % i,
            "interpretation": "A reading.", "symbols": ["a key", "water"], "emotions": ["curious"],
            "emotions_plutchik": ["Anticipation", "Joy"], "people": [], "settings": [], "themes": [],
            "symbol_icons": {"a key": "key", "water": "droplets"}, "emotions_reported": [], "conversation": []}


def test_other_tabs_smoke_with_existing_dreams(browser):
    ctx, page, st = make(browser, dreams=[_dream(i) for i in range(1, 6)])
    for tab, panel in (("archive", "#panel-archive"), ("symbols", "#panel-symbols"), ("patterns", "#panel-patterns"), ("profile", "#panel-profile"), ("home", "#panel-home")):
        page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=\"%s\"], .header-gear-btn[data-tab=\"%s\"]').click()" % (tab, tab))
        page.wait_for_timeout(500)
        assert page.locator(panel).is_visible(), tab
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=\"archive\"]').click()")
    page.wait_for_timeout(500)
    assert "Dream number" in page.locator("#panel-archive").inner_text()
    assert st["errors"] == [], st["errors"]
    ctx.close()
