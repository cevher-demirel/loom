"""Stage 18 browser tests: the unified emotion explorer and the Stage 17 wheel.

Mocked backend only (requests to the API host are intercepted); nothing here
touches a real server. Needs `playwright` with a Chromium install; skipped
automatically when either is missing (e.g. in the pytest-only CI job).
"""
import json
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

INDEX = (Path(__file__).resolve().parents[2] / "index.html").as_uri()
SEP = "\u001e"
FAMILIES = ["happy", "trust", "fear", "surprise", "sad", "disgust", "angry", "anticipation"]


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # no browser installed
            pytest.skip("chromium unavailable: %s" % e)
        yield b
        b.close()


def make(browser, width=390, height=844, delay_ms=0, reduced=False):
    ctx = browser.new_context(viewport={"width": width, "height": height}, has_touch=True, is_mobile=True,
                              reduced_motion="reduce" if reduced else "no-preference")
    page = ctx.new_page()
    st = {"n": 100, "dreams": [], "bodies": [], "fail": False}

    def handler(route):
        r, u = route.request, route.request.url
        if u.endswith("/interpret") and r.method == "POST":
            body = json.loads(r.post_data)
            st["bodies"].append(body)
            if st["fail"]:
                return route.fulfill(status=500, content_type="application/json", body=json.dumps({"detail": "boom"}))
            st["n"] += 1
            meta = {"id": st["n"], "symbols": ["a key"], "emotions": ["curious"], "people": [], "settings": [], "themes": [],
                    "interpretation": "A reading of your dream.", "symbol_icons": {"a key": "key"},
                    "emotions_reported": body.get("emotions_reported", []), "emotions_plutchik": ["Anticipation"], "similar": []}
            st["dreams"].append({"id": st["n"], "timestamp": "2025-11-01T08:00:00Z", "raw_text": body["raw_text"],
                                 "interpretation": meta["interpretation"], "symbols": ["a key"], "emotions": ["curious"],
                                 "emotions_plutchik": ["Anticipation"], "people": [], "settings": [], "themes": [],
                                 "symbol_icons": {"a key": "key"}, "emotions_reported": meta["emotions_reported"], "conversation": []})
            return route.fulfill(status=200, content_type="text/plain", body="A reading." + SEP + json.dumps(meta))
        if "/dreams" in u and r.method == "GET" and "/dreams/" not in u:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(st["dreams"]))
        route.fulfill(status=200, content_type="application/json", body="[]" if "/personal-meanings" in u else "{}")

    page.route("**://loom-phas.onrender.com/**", handler)
    page.add_init_script("window.__of=window.fetch;window.fetch=function(u,o){if(String(u).indexOf('/interpret')>-1&&%d){return new Promise(function(r){setTimeout(r,%d)}).then(function(){return window.__of(u,o)})}return window.__of(u,o)};" % (delay_ms, delay_ms))
    page.add_init_script("localStorage.setItem('loom_token','tok');localStorage.setItem('loom_username','Tester');")
    page.goto(INDEX)
    page.wait_for_selector("#app-shell:not([hidden])")
    page.wait_for_timeout(600)
    return ctx, page, st


def to_explorer(page, text="A key in a long hallway of doors."):
    page.evaluate("document.getElementById('home-record-btn').click()")
    page.fill("#dream-input", text)
    page.click("#interpret-btn")
    page.wait_for_selector(".feel-tabs")


def pick(page, fam, mid_idx=0, leaf_idx=0):
    page.click('.feel-tile[data-feel-family="%s"]' % fam)
    page.locator("[data-feel-mid]").nth(mid_idx).click()
    page.locator(".feel-leaf[data-feel-toggle]").nth(leaf_idx + 1).click()


def test_continue_opens_unified_explorer_by_category_default(browser):
    ctx, page, _ = make(browser)
    to_explorer(page)
    assert page.locator(".feel-choice").count() == 0
    assert page.locator('.feel-tab.on').inner_text() == "By Category"
    assert page.locator(".feel-tile").count() == 8
    assert page.locator(".feel-bloom").count() == 1
    assert page.locator("#feel-skip-btn").is_visible()
    ctx.close()


def test_switch_views_preserves_selection_and_never_submits(browser):
    ctx, page, st = make(browser)
    to_explorer(page)
    pick(page, "fear")
    page.click("[data-feel-done]")
    page.click('.feel-tab[data-feel-view="wheel"]')
    assert page.locator('path[data-feel-family="fear"]').get_attribute("aria-label") == "Fear, 1 selected"
    page.click('.feel-tab[data-feel-view="category"]')
    assert page.locator(".feel-tile[data-feel-family='fear'] .feel-badge").inner_text() == "1"
    assert "Add to Dream (1)" in page.locator("#feel-go-btn").inner_text()
    assert st["bodies"] == []
    ctx.close()


@pytest.mark.parametrize("view", ["category", "wheel"])
def test_family_detail_from_either_view_and_back(browser, view):
    ctx, page, _ = make(browser)
    to_explorer(page)
    if view == "wheel":
        page.click('.feel-tab[data-feel-view="wheel"]')
        page.click('path[data-feel-family="sad"]', force=True)
    else:
        page.click('.feel-tile[data-feel-family="sad"]')
    assert "feel-fam-desc" in page.content()
    assert page.locator("#feel-skip-btn").is_hidden()
    page.click("#feel-back-btn")
    assert page.locator('.feel-tab.on').inner_text() == ("Emotion Wheel" if view == "wheel" else "By Category")
    assert page.locator(".feel-fam-head").count() == 0
    ctx.close()


def test_back_to_record_keeps_draft_and_selection_and_view(browser):
    ctx, page, _ = make(browser)
    to_explorer(page, "draft text here")
    page.click('.feel-tab[data-feel-view="wheel"]')
    page.click('path[data-feel-family="happy"]', force=True)
    page.locator("[data-feel-mid]").first.click()
    page.locator(".feel-leaf[data-feel-toggle]").nth(1).click()
    page.click("[data-feel-done]")
    page.click("#feel-back-btn")
    assert page.input_value("#dream-input") == "draft text here"
    page.click("#interpret-btn")
    assert page.locator('.feel-tab.on').inner_text() == "Emotion Wheel"
    assert "Add to Dream (1)" in page.locator("#feel-go-btn").inner_text()
    ctx.close()


def test_add_to_selection_returns_without_submitting_and_expanding_selects_nothing(browser):
    ctx, page, st = make(browser)
    to_explorer(page)
    page.click('.feel-tile[data-feel-family="trust"]')
    page.locator("[data-feel-mid]").nth(0).click()
    page.locator("[data-feel-mid]").nth(1).click()
    assert page.locator(".feel-leaf.selected").count() == 0
    page.locator(".feel-leaf[data-feel-toggle]").nth(1).click()
    page.click("[data-feel-done]")
    assert page.locator(".feel-tile").count() == 8 and st["bodies"] == []
    ctx.close()


def test_add_to_dream_submits_once_even_on_double_tap(browser):
    ctx, page, st = make(browser, delay_ms=700)
    to_explorer(page)
    pick(page, "fear")
    page.click("[data-feel-done]")
    page.evaluate("var b=document.getElementById('feel-go-btn');b.click();b.click();")
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    assert len(st["bodies"]) == 1
    assert st["bodies"][0]["emotions_reported"][0] == "Fear"
    ctx.close()


def test_skip_sends_original_request(browser):
    ctx, page, st = make(browser)
    to_explorer(page, "plain dream")
    pick(page, "fear")
    page.click("[data-feel-done]")
    page.click("#feel-skip-btn")
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    assert st["bodies"] == [{"raw_text": "plain dream"}]
    ctx.close()


def test_failure_preserves_draft_and_retry_creates_one_dream(browser):
    ctx, page, st = make(browser)
    st["fail"] = True
    to_explorer(page, "retry me")
    pick(page, "sad")
    page.click("[data-feel-done]")
    page.click("#feel-go-btn")
    page.wait_for_selector("#interp-wait.failed", timeout=10000)
    st["fail"] = False
    page.click("#iw-retry-btn")
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    assert len(st["dreams"]) == 1
    assert st["bodies"][0] == st["bodies"][1]
    ctx.close()


def test_new_dream_does_not_inherit_selection_or_view(browser):
    ctx, page, st = make(browser)
    to_explorer(page)
    page.click('.feel-tab[data-feel-view="wheel"]')
    page.click('path[data-feel-family="happy"]', force=True)
    page.locator("[data-feel-mid]").first.click()
    page.locator(".feel-leaf[data-feel-toggle]").nth(1).click()
    page.click("[data-feel-done]")
    page.click("#feel-go-btn")
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    page.click("#dream-screen-back-btn")
    page.evaluate("document.querySelector('[data-tab=home]').click()")
    page.evaluate("document.getElementById('home-record-btn').click()")
    page.fill("#dream-input", "another dream")
    page.click("#interpret-btn")
    assert page.locator('.feel-tab.on').inner_text() == "By Category"
    assert page.locator("#feel-go-btn").count() == 0
    ctx.close()


def test_all_families_expose_full_hierarchy(browser):
    ctx, page, _ = make(browser)
    to_explorer(page)
    mids = leaves = checks = 0
    for fam in FAMILIES:
        page.click('.feel-tile[data-feel-family="%s"]' % fam)
        n = page.locator("[data-feel-mid]").count()
        for i in range(n):
            page.locator("[data-feel-mid]").nth(i).click()
        mids += n
        leaves += page.locator(".feel-leaf[data-feel-toggle]").count()
        checks += page.locator(".feel-check").count()
        names = page.locator(".feel-mid-leaves .feel-leaf").all_inner_texts()
        for mid in page.locator(".feel-mid").all():
            heading = mid.locator(".feel-mid-name span").first.inner_text()
            assert heading not in mid.locator(".feel-leaf").all_inner_texts(), heading
            assert mid.locator(".feel-leaf").count() == 2
        page.click("[data-feel-done]")
    # one heading + one check per group, two child chips each, plus one family chip per family
    assert mids == 40 and checks == 40 and leaves == 8 + 80
    ctx.close()


@pytest.mark.parametrize("w,h", [(320, 640), (375, 667), (390, 844), (430, 932), (390, 600)])
def test_wheel_geometry_and_responsive(browser, w, h):
    ctx, page, _ = make(browser, w, h)
    to_explorer(page)
    page.click('.feel-tab[data-feel-view="wheel"]')
    page.wait_for_timeout(200)
    r = page.evaluate("""() => {
      const svg = document.querySelector('.feel-wheel'), sr = svg.getBoundingClientRect();
      const core = [...svg.querySelectorAll('circle')].find(c => c.getAttribute('r') === '46').getBoundingClientRect();
      const star = svg.querySelector('.fw-star'), crescent = svg.querySelector('path[fill="url(#fw-moon)"]');
      const out = { sw: document.documentElement.scrollWidth, iw: innerWidth, size: sr.width, star: !!star && star.getBoundingClientRect().width > 0, moon: !!crescent, segs: [] };
      const grps = [...svg.querySelectorAll('.fw-grp')];
      svg.querySelectorAll('path[data-feel-family]').forEach((path, i) => {
        const id = path.dataset.feelFamily, g = grps[i], t = g.querySelector('text').getBoundingClientRect(), ic = g.querySelector('g').getBoundingClientRect();
        const pts = [[t.left+1,t.top+t.height/2],[t.right-1,t.top+t.height/2],[t.left+t.width/2,t.top+1],[t.left+t.width/2,t.bottom-1],[ic.left+ic.width/2,ic.top+2],[ic.left+2,ic.bottom-2],[ic.right-2,ic.bottom-2]];
        const inside = pts.every(([x, y]) => { const e = document.elementsFromPoint(x, y).find(el => el.dataset && el.dataset.feelFamily); return e && e.dataset.feelFamily === id; });
        const cx = core.left + core.width/2, cy = core.top + core.height/2, rr = core.width/2;
        const nearest = (b) => { const x = Math.max(b.left, Math.min(cx, b.right)), y = Math.max(b.top, Math.min(cy, b.bottom)); return Math.hypot(x-cx, y-cy); };
        out.segs.push({ id, inside, name: g.querySelector('text').textContent, iconAbove: ic.bottom <= t.top + 1, centered: Math.abs((ic.left+ic.right)/2 - (t.left+t.right)/2) < 2,
          inView: t.left >= sr.left && t.right <= sr.right && t.top >= sr.top && t.bottom <= sr.bottom, clearOfCore: nearest(t) > rr && nearest(ic) > rr, tb: [t.left,t.top,t.right,t.bottom], ib: [ic.left,ic.top,ic.right,ic.bottom] });
      });
      return out; }""")
    assert r["sw"] <= r["iw"] and r["star"] and r["moon"]
    assert r["size"] >= (280 if w <= 320 else 330)
    assert len(r["segs"]) == 8
    for s in r["segs"]:
        assert s["inside"] and s["iconAbove"] and s["centered"] and s["inView"] and s["clearOfCore"], s["id"]
    for i in range(8):
        for j in range(i + 1, 8):
            a, b = r["segs"][i]["tb"], r["segs"][j]["tb"]
            assert a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1]
    # every segment opens from a tap on its label and on its icon
    for k, s in enumerate(r["segs"]):
        for which in ("text", "g"):
            page.evaluate("document.querySelectorAll('.feel-wheel .fw-grp')[%d].scrollIntoView({block:'center'})" % k)
            box = page.evaluate("(()=>{const e=document.querySelectorAll('.feel-wheel .fw-grp')[%d].querySelector('%s').getBoundingClientRect();return [e.left+e.width/2,e.top+e.height/2]})()" % (k, which))
            page.mouse.click(*box)
            assert page.locator("path.focus").get_attribute("data-feel-family") == s["id"], (s["id"], which)
            page.click("#feel-back-btn") if False else page.evaluate("document.querySelector('[data-feel-done]').click()")
    ctx.close()


def test_wheel_keyboard_names_and_reduced_motion(browser):
    ctx, page, _ = make(browser, reduced=True)
    to_explorer(page)
    page.click('.feel-tab[data-feel-view="wheel"]')
    names = page.evaluate("[...document.querySelectorAll('path[data-feel-family]')].map(e => e.getAttribute('aria-label'))")
    assert len(names) == 8 and all(names)
    page.focus('path[data-feel-family="fear"]')
    page.keyboard.press("Enter")
    assert page.locator("path.focus").get_attribute("data-feel-family") == "fear"
    assert page.evaluate("getComputedStyle(document.querySelector('.fw-star')).animationName") == "none"
    ctx.close()


def test_parent_and_children_select_independently(browser):
    ctx, page, _ = make(browser)
    to_explorer(page)
    page.click('.feel-tile[data-feel-family="fear"]')
    first = page.locator(".feel-mid").first
    first.locator("[data-feel-mid]").click()
    assert page.locator(".feel-leaf.selected, .feel-check.on").count() == 0       # expanding selects nothing
    first.locator(".feel-check").click()
    assert first.locator(".feel-check").get_attribute("aria-checked") == "true"
    assert first.locator(".feel-leaf.selected").count() == 0                        # parent does not select children
    first.locator(".feel-leaf").nth(0).click()
    assert first.locator(".feel-check").get_attribute("aria-checked") == "true"    # child does not deselect parent
    first.locator(".feel-check").click()
    assert first.locator(".feel-leaf.selected").count() == 1                        # nor parent change children
    assert page.locator(".feel-tray-row").count() == 1
    ctx.close()


@pytest.mark.parametrize("w,h", [(320, 640), (375, 667), (390, 844), (430, 932), (390, 600)])
def test_explorer_layout_no_overflow_actions_clear_nav_touch_targets(browser, w, h):
    ctx, page, _ = make(browser, w, h)
    to_explorer(page)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.click('.feel-tile[data-feel-family="anticipation"]')
    for i in range(page.locator("[data-feel-mid]").count()):
        page.locator("[data-feel-mid]").nth(i).click()
    page.locator(".feel-leaf[data-feel-toggle]").nth(2).click()
    page.evaluate("window.scrollTo(0, 0)")
    r = page.evaluate("""() => {
      const nav = document.getElementById('bottom-tabs-nav').getBoundingClientRect(), a = document.querySelector('.feel-actions').getBoundingClientRect();
      const small = [...document.querySelectorAll('.feel-check, .feel-mid-name, .feel-tab, .feel-leaf, [data-feel-done]')].filter(e => e.getBoundingClientRect().height < 43).length;
      return { overflow: document.documentElement.scrollWidth > innerWidth, actionsBottom: a.bottom, navTop: nav.top, small, vh: innerHeight };
    }""")
    assert not r["overflow"] and r["small"] == 0
    assert r["actionsBottom"] <= r["navTop"] + 1          # sticky Add to Selection stays above the nav
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    assert page.evaluate("document.querySelector('.feel-actions').getBoundingClientRect().bottom <= document.getElementById('bottom-tabs-nav').getBoundingClientRect().top + 1")
    ctx.close()
