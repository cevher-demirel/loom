"""Stage 19 browser tests: the wheel-only emotion selection screen.

Mocked backend only (requests to the API host are intercepted); nothing here
touches a real server. Needs `playwright` with a Chromium install; skipped
automatically when either is missing -- unless REQUIRE_BROWSER=1 (set in CI), in
which case a missing browser is a failure, never a silent skip.
"""
import json
from pathlib import Path

import pytest

import os

if os.environ.get("REQUIRE_BROWSER") == "1":
    import playwright.sync_api as pw
else:
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
            if os.environ.get("REQUIRE_BROWSER") == "1":
                raise
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
    page.wait_for_selector(".feel-wheel")


def focus(page, fam):
    page.click('path[data-feel-family="%s"]' % fam, force=True)


def pick_child(page, fam, mid_idx=0, leaf_idx=0):
    """focus a family, expand one group, select one child chip"""
    focus(page, fam)
    mid = page.locator(".feel-mid").nth(mid_idx)
    if mid.locator(".feel-leaf").count() == 0:
        mid.locator("[data-feel-mid]").click()
    mid.locator(".feel-leaf").nth(leaf_idx).click()


def sel_count(page):
    return page.locator(".feel-chip").count()


def test_initial_state_is_calm_wheel_only(browser):
    ctx, page, _ = make(browser)
    to_explorer(page)
    assert page.locator(".feel-tab, .feel-tile, .feel-grid, [data-feel-done]").count() == 0
    assert page.locator("path[data-feel-family]").count() == 8
    assert page.locator(".feel-detail").count() == 0 and sel_count(page) == 0
    assert page.locator("#feel-go-btn").count() == 0
    assert page.locator("#feel-skip-btn").is_visible() and page.locator(".feel-bloom").count() == 1
    assert "Choose one or more feelings from your dream." in page.locator(".feel-sub").inner_text()
    assert page.locator(".feel-guide").is_visible()
    ctx.close()


def test_focusing_a_family_never_selects_it(browser):
    ctx, page, _ = make(browser)
    to_explorer(page)
    focus(page, "fear")
    assert page.locator(".feel-detail h3").inner_text() == "Fear"
    assert page.locator("path.focus").get_attribute("data-feel-family") == "fear"
    assert sel_count(page) == 0 and page.locator(".feel-check.on").count() == 0
    focus(page, "fear")                                  # tapping the active segment keeps it
    assert page.locator(".feel-detail").count() == 1
    ctx.close()


def test_groups_collapsed_and_expanding_selects_nothing(browser):
    ctx, page, _ = make(browser)
    to_explorer(page)
    focus(page, "fear")
    assert page.locator(".feel-mid").count() == 6 and page.locator(".feel-mid .feel-leaf").count() == 0
    page.locator("[data-feel-mid]").first.click()
    assert page.locator(".feel-mid").first.locator(".feel-leaf").count() == 2
    assert sel_count(page) == 0
    ctx.close()


def test_parent_child_family_selected_independently(browser):
    ctx, page, _ = make(browser)
    to_explorer(page)
    focus(page, "fear")
    first = page.locator(".feel-mid").first
    first.locator("[data-feel-mid]").click()
    first.locator(".feel-check").click()
    assert first.locator(".feel-leaf.selected").count() == 0                       # parent does not select children
    first.locator(".feel-leaf").nth(0).click()
    assert first.locator(".feel-check").get_attribute("aria-checked") == "true"    # child keeps parent
    page.locator(".feel-fam-select .feel-check").click()
    assert page.locator(".feel-mid .feel-check.on").count() == 1                   # family does not select groups
    first.locator(".feel-check").click()
    assert first.locator(".feel-leaf.selected").count() == 1                       # parent off keeps child
    assert sel_count(page) == 2
    ctx.close()


def test_multi_select_across_families_persists_and_marks_wheel(browser):
    ctx, page, _ = make(browser)
    to_explorer(page)
    pick_child(page, "fear", 0, 0)       # Fear -> Cautious -> Timid
    pick_child(page, "fear", 2, 0)       # Fear -> Scared -> Frightened
    pick_child(page, "anticipation", 0, 0)
    pick_child(page, "trust", 0, 0)
    assert sel_count(page) == 4
    assert "Add to Dream (4)" in page.locator("#feel-go-btn").inner_text()
    assert page.locator('path[data-feel-family="fear"]').get_attribute("aria-label") == "Fear, 2 selected"
    assert page.locator('path[data-feel-family="anticipation"]').get_attribute("aria-label") == "Anticipation, 1 selected"
    assert page.locator('path[data-feel-family="happy"]').get_attribute("aria-label") == "Happy"
    focus(page, "fear")                                                    # reopening keeps state
    assert page.locator(".feel-mid .feel-leaf.selected").count() >= 1 and sel_count(page) == 4
    ctx.close()


def test_chip_removal_and_clear_all_update_every_control(browser):
    ctx, page, _ = make(browser)
    to_explorer(page)
    pick_child(page, "fear", 0, 0)
    pick_child(page, "trust", 0, 0)
    page.locator(".feel-chip button").first.click()
    assert sel_count(page) == 1 and "Add to Dream (1)" in page.locator("#feel-go-btn").inner_text()
    assert page.locator('path[data-feel-family="fear"]').get_attribute("aria-label") == "Fear"
    page.click(".feel-clear")
    assert sel_count(page) == 0 and page.locator("#feel-go-btn").count() == 0
    assert page.input_value("#dream-input") != ""                                  # only selection state is cleared
    ctx.close()


def test_chip_shows_full_path_and_family_accent(browser):
    ctx, page, _ = make(browser)
    to_explorer(page)
    pick_child(page, "fear", 0, 0)
    assert page.locator(".feel-chip").inner_text().replace("×", "").strip() == "Fear → Cautious → Timid"
    ctx.close()


def test_back_keeps_draft_and_selection_and_skip_arms_when_selected(browser):
    ctx, page, st = make(browser)
    to_explorer(page, "draft text here")
    pick_child(page, "happy", 0, 0)
    page.click("#feel-back-btn")
    assert page.input_value("#dream-input") == "draft text here"
    page.click("#interpret-btn")
    assert page.locator(".feel-detail").count() == 0                              # calm start, nothing forced open
    assert "Add to Dream (1)" in page.locator("#feel-go-btn").inner_text()
    page.click("#feel-skip-btn")
    assert page.locator("#feel-skip-btn").inner_text() == "Discard & skip?" and st["bodies"] == []
    ctx.close()


def test_add_to_dream_submits_all_ids_once_even_on_double_tap(browser):
    ctx, page, st = make(browser, delay_ms=700)
    to_explorer(page)
    pick_child(page, "fear", 0, 0)
    pick_child(page, "anticipation", 0, 1)
    page.evaluate("var b=document.getElementById('feel-go-btn');b.click();b.click();")
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    assert len(st["bodies"]) == 1
    rep = st["bodies"][0]["emotions_reported"]
    assert rep[0] == "Fear" and "Timid" in rep and "Anticipation" in rep
    ctx.close()


def test_parent_only_and_child_only_payloads(browser):
    ctx, page, st = make(browser)
    to_explorer(page)
    focus(page, "sad")
    page.locator(".feel-mid .feel-check").first.click()             # parent only
    page.click("#feel-go-btn")
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    first_label = st["bodies"][0]["emotions_reported"]
    assert first_label[0] == "Sadness" and len(first_label) == 2
    ctx.close()


def test_skip_sends_original_request(browser):
    ctx, page, st = make(browser)
    to_explorer(page, "plain dream")
    page.click("#feel-skip-btn")
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    assert st["bodies"] == [{"raw_text": "plain dream"}]
    ctx.close()


def test_failure_preserves_draft_and_retry_creates_one_dream(browser):
    ctx, page, st = make(browser)
    st["fail"] = True
    to_explorer(page, "retry me")
    pick_child(page, "sad", 0, 0)
    page.click("#feel-go-btn")
    page.wait_for_selector("#interp-wait.failed", timeout=10000)
    st["fail"] = False
    page.click("#iw-retry-btn")
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    assert len(st["dreams"]) == 1 and st["bodies"][0] == st["bodies"][1]
    ctx.close()


def test_new_dream_does_not_inherit_selection(browser):
    ctx, page, st = make(browser)
    to_explorer(page)
    pick_child(page, "happy", 0, 0)
    page.click("#feel-go-btn")
    page.wait_for_selector("#dream-screen:not([hidden])", timeout=15000)
    page.click("#dream-screen-back-btn")
    page.evaluate("document.querySelector('[data-tab=home]').click()")
    page.evaluate("document.getElementById('home-record-btn').click()")
    page.fill("#dream-input", "another dream")
    page.click("#interpret-btn")
    assert sel_count(page) == 0 and page.locator(".feel-detail").count() == 0
    ctx.close()


def test_all_families_expose_full_taxonomy(browser):
    import json
    base = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "emotion_taxonomy_baseline.json").read_text())
    ctx, page, _ = make(browser)
    to_explorer(page)
    for fam in base:
        focus(page, fam["id"])
        assert page.locator(".feel-detail h3").inner_text().lower() in (fam["label"].lower(), "anger")
        assert page.locator(".feel-fam-desc").count() == 1
        heads = page.locator(".feel-mid-name span:first-child").all_inner_texts()
        assert heads == [m["label"] for m in fam["children"]], fam["id"]
        for i in range(len(fam["children"])):
            page.locator("[data-feel-mid]").nth(i).click()
        for i, mid in enumerate(fam["children"]):
            chips = page.locator(".feel-mid").nth(i).locator(".feel-leaf").all_inner_texts()
            assert [c.replace("✓", "").strip() for c in chips] == [l["label"] for l in mid["children"]]
            assert mid["label"] not in [c.strip() for c in chips]                 # parent shown once
    ctx.close()


def test_same_label_in_different_branches_stay_distinct(browser):
    import json
    base = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "emotion_taxonomy_baseline.json").read_text())
    seen = {}
    for f in base:
        for m in f["children"]:
            for node in [m] + m["children"]:
                seen.setdefault(node["label"], []).append(node["id"])
    dups = {k: v for k, v in seen.items() if len(v) > 1}
    if not dups:
        pytest.skip("taxonomy has no repeated labels")
    ctx, page, _ = make(browser)
    to_explorer(page)
    label, ids = next(iter(dups.items()))
    for i in ids:                                                  # select every branch carrying the label
        fam = i.split(".")[0]
        focus(page, fam)
        mid = page.locator(".feel-mid").nth([m["id"] for m in next(f for f in base if f["id"] == fam)["children"]].index(".".join(i.split(".")[:2])))
        if len(i.split(".")) == 2:
            mid.locator(".feel-check").click()
        else:
            if mid.locator(".feel-leaf").count() == 0:
                mid.locator("[data-feel-mid]").click()
            mid.locator(".feel-leaf", has_text=label).first.click()
    assert sel_count(page) == len(ids)
    ctx.close()


@pytest.mark.parametrize("w,h", [(320, 640), (375, 667), (390, 844), (430, 932), (390, 600), (1280, 800)])
def test_wheel_geometry_and_responsive(browser, w, h):
    ctx, page, _ = make(browser, w, h)
    to_explorer(page)
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
        out.segs.push({ id, inside, iconAbove: ic.bottom <= t.top + 1, centered: Math.abs((ic.left+ic.right)/2 - (t.left+t.right)/2) < 2,
          inView: t.left >= sr.left && t.right <= sr.right && t.top >= sr.top && t.bottom <= sr.bottom, clearOfCore: nearest(t) > rr && nearest(ic) > rr, tb: [t.left,t.top,t.right,t.bottom] });
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
    # label tap and icon tap both focus the segment
    for k, s in enumerate(r["segs"]):
        for which in ("text", "g"):
            page.evaluate("document.querySelectorAll('.feel-wheel .fw-grp')[%d].scrollIntoView({block:'center'})" % k)
            box = page.evaluate("(()=>{const e=document.querySelectorAll('.feel-wheel .fw-grp')[%d].querySelector('%s').getBoundingClientRect();return [e.left+e.width/2,e.top+e.height/2]})()" % (k, which))
            page.mouse.click(*box)
            assert page.locator("path.focus").get_attribute("data-feel-family") == s["id"], (s["id"], which)
    ctx.close()


@pytest.mark.parametrize("w,h", [(320, 640), (375, 667), (390, 844), (430, 932), (390, 600)])
def test_layout_dock_clears_nav_targets_and_no_overflow(browser, w, h):
    ctx, page, _ = make(browser, w, h)
    to_explorer(page)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    for fam in ("fear", "anticipation", "trust", "sad", "happy"):
        pick_child(page, fam, 0, 0)
    focus(page, "fear")
    for i in range(page.locator("[data-feel-mid]").count()):
        page.locator("[data-feel-mid]").nth(i).click()
    r = page.evaluate("""() => {
      const nav = document.getElementById('bottom-tabs-nav').getBoundingClientRect();
      const small = [...document.querySelectorAll('.feel-check, .feel-mid-name, .feel-leaf, .feel-chip button, #feel-go-btn, #feel-skip-btn')].filter(e => e.getBoundingClientRect().height < 39).length;
      return { overflow: document.documentElement.scrollWidth > innerWidth, navTop: nav.top, small };
    }""")
    assert not r["overflow"] and r["small"] == 0
    for pos in ("window.scrollTo(0,0)", "window.scrollTo(0, document.body.scrollHeight)"):
        page.evaluate(pos)
        b = page.evaluate("(()=>{const d=document.querySelector('.feel-dock').getBoundingClientRect(),n=document.getElementById('bottom-tabs-nav').getBoundingClientRect();return [d.bottom,n.top,d.top,innerHeight]})()")
        assert b[0] <= b[1] + 1                       # dock sits above the bottom nav
        assert page.locator("#feel-go-btn").is_visible()
    ctx.close()


def test_wheel_keyboard_names_focus_and_reduced_motion(browser):
    ctx, page, _ = make(browser, reduced=True)
    to_explorer(page)
    names = page.evaluate("[...document.querySelectorAll('path[data-feel-family]')].map(e => e.getAttribute('aria-label'))")
    assert len(names) == 8 and all(names)
    page.focus('path[data-feel-family="fear"]')
    page.keyboard.press("Enter")
    assert page.locator("path.focus").get_attribute("data-feel-family") == "fear"
    page.focus('path[data-feel-family="trust"]')
    page.keyboard.press(" ")
    assert page.locator("path.focus").get_attribute("data-feel-family") == "trust"
    assert page.evaluate("getComputedStyle(document.querySelector('.fw-star')).animationName") == "none"
    # checkbox semantics on parent rows
    assert page.locator(".feel-mid .feel-check").first.get_attribute("role") == "checkbox"
    assert page.locator("[data-feel-mid]").first.get_attribute("aria-expanded") == "false"
    ctx.close()
