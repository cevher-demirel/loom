import sys, os, json, traceback
sys.path.insert(0, "/home/claude/cevher-demirel/loom"); sys.path.insert(0, os.path.dirname(__file__))
from tests.browser.harness import make as _make, to_explorer, pick_child, INDEX
from playwright.sync_api import sync_playwright
import seed
OUT = "/home/claude/cevher-demirel/loom/docs/audit/stage22/screenshots/"
VPS = [(320,568),(375,667),(390,844),(430,932),(768,1024),(1280,800)]
LOG = []
def make(b, w, h, **kw):
    ctx, pg, st = _make(b, w, h, **kw)
    pg.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)   # splash holds ~2.2s on every cold open
    pg.wait_for_timeout(500)
    return ctx, pg, st
def S(pg, area, name, w, h, full=False):
    os.makedirs(OUT + area, exist_ok=True)
    pg.screenshot(path=OUT + "%s/%s_%dx%d.png" % (area, name, w, h), full_page=full)
    LOG.append("%s/%s_%dx%d" % (area, name, w, h))
def tab(pg, t):
    pg.evaluate("(t)=>{const b=document.querySelector('.bottom-tab-btn[data-tab=\"'+t+'\"]')||document.querySelector('.side-nav-btn[data-tab=\"'+t+'\"]');b.click()}", t)
    pg.wait_for_timeout(900)
def step(label, fn):
    try: fn()
    except Exception as e: LOG.append("FAILED %s: %s" % (label, str(e).splitlines()[0][:120]))
def settle(pg, ms=500): pg.wait_for_timeout(ms)

def flow(b, w, h):
    # ---- populated session (30 dreams) -------------------------------
    ctx, pg, st = make(b, w, h, dreams=seed.dreams(30))
    step("home", lambda: S(pg, "01_home", "home_populated", w, h))
    step("home_full", lambda: S(pg, "01_home", "home_populated_full", w, h, True))
    def rec():
        pg.evaluate("document.getElementById('home-record-btn').click()"); settle(pg, 700); S(pg, "02_record", "entry_empty", w, h)
        pg.fill("#dream-input", "I was holding a brass key in a long hallway of doors. My sister was waiting at the end and I felt both afraid and hopeful."); settle(pg, 900); S(pg, "02_record", "entry_typed", w, h)
        pg.click("#interpret-btn"); pg.wait_for_selector(".feel-wheel"); settle(pg, 700); S(pg, "03_wheel", "initial", w, h)
        pg.click('path[data-feel-family="fear"]', force=True); settle(pg, 600); S(pg, "03_wheel", "focused_family", w, h)
        pick_child(pg, "fear", 0, 0); pick_child(pg, "trust", 0, 0); pick_child(pg, "sad", 0, 0); settle(pg, 400); S(pg, "03_wheel", "several_selected", w, h)
        pg.click("[data-feel-tray]"); settle(pg, 400); S(pg, "03_wheel", "tray_expanded", w, h)
        pg.click("[data-feel-tray]")
        st["fail_once"] = 1; pg.click("#feel-go-btn"); pg.wait_for_selector("#interp-wait.failed", timeout=10000); settle(pg, 400); S(pg, "04_interpret", "recoverable_error", w, h)
        pg.click("#iw-retry-btn"); pg.wait_for_selector("#dream-screen:not([hidden])", timeout=15000); settle(pg, 700); S(pg, "05_dream_detail", "after_submit", w, h); S(pg, "05_dream_detail", "after_submit_full", w, h, True)
    step("record flow", rec)
    ctx.close()
    ctx, pg, st = make(b, w, h, dreams=seed.dreams(30))
    def interp():
        to_explorer(pg, "A key."); pick_child(pg, "fear", 0, 0); st["hang_ms"] = 6000; pg.click("#feel-go-btn"); settle(pg, 1800); S(pg, "04_interpret", "interpreting", w, h)
    step("interpreting", interp); ctx.close()
    ctx, pg, st = make(b, w, h, dreams=seed.dreams(30))
    def journal():
        tab(pg, "archive"); S(pg, "06_journal", "populated", w, h); S(pg, "06_journal", "populated_full", w, h, True)
        pg.fill("#archive-search-input", "key"); settle(pg, 600); S(pg, "06_journal", "search_key", w, h)
        pg.fill("#archive-search-input", "zzzz"); settle(pg, 600); S(pg, "06_journal", "search_no_results", w, h); pg.fill("#archive-search-input", ""); settle(pg, 300)
        pg.click('[data-filter="emotions"]'); settle(pg, 500); S(pg, "06_journal", "filter_emotions", w, h)
        pg.click('[data-filter="all"]')
        pg.locator("#archive-list > *").first.click(); settle(pg, 900); S(pg, "05_dream_detail", "from_journal", w, h); S(pg, "05_dream_detail", "from_journal_full", w, h, True)
    step("journal", journal)
    ctx.close()
    # ---- Loom Map ------------------------------------------------------
    ctx, pg, st = make(b, w, h, dreams=seed.dreams(30))
    def loom():
        tab(pg, "symbols"); settle(pg, 1200); S(pg, "07_loom_map", "network_30", w, h); S(pg, "07_loom_map", "network_30_full", w, h, True)
        pg.locator(".loom-graph-node--symbol").first.click(); settle(pg, 900); S(pg, "07_loom_map", "selected_node", w, h)
        step("close", lambda: pg.evaluate("document.getElementById('loom-preview-node-close-btn')&&document.getElementById('loom-preview-node-close-btn').click()")); settle(pg, 500)
        pg.locator(".loom-graph-node--symbol").first.click(); settle(pg, 700)
        pg.locator("#loom-preview-connected-grid button").first.click(); settle(pg, 900); S(pg, "07_loom_map", "selected_connection", w, h)
        pg.evaluate("(()=>{const e=document.getElementById('loom-preview-explore-btn');})()")
        pg.keyboard.press("Escape"); settle(pg, 500)
        pg.click("#loom-map-filter-btn"); settle(pg, 800); S(pg, "07_loom_map", "filters_sheet", w, h); pg.keyboard.press("Escape"); settle(pg, 500)
        pg.click("#loom-view-timeline-btn"); settle(pg, 800); S(pg, "07_loom_map", "timeline_picker", w, h)
        pg.click("#loom-view-list-btn"); settle(pg, 800); S(pg, "07_loom_map", "list", w, h); S(pg, "07_loom_map", "list_full", w, h, True)
    step("loom", loom); ctx.close()
    for n in (3, 120):
        ctx, pg, st = make(b, w, h, dreams=seed.dreams(n))
        def m():
            tab(pg, "symbols"); settle(pg, 1400); S(pg, "07_loom_map", "network_%d" % n, w, h)
        step("loom%d" % n, m); ctx.close()
    ctx, pg, st = make(b, w, h, dreams=[])
    def loom0():
        tab(pg, "symbols"); settle(pg, 900); S(pg, "07_loom_map", "network_empty", w, h)
        tab(pg, "archive"); settle(pg, 700); S(pg, "06_journal", "empty", w, h)
        tab(pg, "patterns"); settle(pg, 900); S(pg, "08_insights", "empty", w, h)
        tab(pg, "home"); settle(pg, 700); S(pg, "01_home", "home_empty", w, h)
    step("empty", loom0); ctx.close()
    # ---- Insights ------------------------------------------------------
    for n in (30, 3):
        ctx, pg, st = make(b, w, h, dreams=seed.dreams(n))
        def ins():
            tab(pg, "patterns"); settle(pg, 1200); S(pg, "08_insights", "populated_%d" % n, w, h); S(pg, "08_insights", "populated_%d_full" % n, w, h, True)
        step("insights%d" % n, ins); ctx.close()
    # ---- Profile / Settings --------------------------------------------
    ctx, pg, st = make(b, w, h, dreams=seed.dreams(5))
    def prof():
        pg.evaluate("document.querySelector('.header-gear-btn, .side-nav-btn--gear').click()"); settle(pg, 900); S(pg, "09_profile", "top", w, h); S(pg, "09_profile", "full", w, h, True)
        pg.evaluate("(()=>{const b=[...document.querySelectorAll('#panel-profile button')].find(x=>/delete/i.test(x.textContent));b&&b.click()})()"); settle(pg, 700); S(pg, "09_profile", "delete_confirm", w, h)
    step("profile", prof); ctx.close()
    # ---- Auth (logged out) ----------------------------------------------
    c2 = b.new_context(viewport={"width": w, "height": h}, is_mobile=True, has_touch=True); p2 = c2.new_page()
    p2.route("**://loom-phas.onrender.com/**", lambda r: r.fulfill(status=200, content_type="application/json", body="{}"))
    def auth():
        p2.goto(INDEX); p2.wait_for_timeout(3500); S(p2, "10_auth", "landing", w, h)
        for sel, nm in (("#auth-panel-signup", "signup"), ("#auth-panel-forgot", "forgot")):
            p2.evaluate("(()=>{const b=[...document.querySelectorAll('#auth-shell button, #auth-shell a')].find(x=>/%s/i.test(x.textContent));b&&b.click()})()" % ("sign up|create" if nm == "signup" else "forgot")); p2.wait_for_timeout(700); S(p2, "10_auth", nm, w, h)
    step("auth", auth); c2.close()

def extras(b):
    # short-height + landscape + keyboard-open emulation
    for (w, h, tag) in ((390, 600, "short"), (844, 390, "landscape"), (390, 420, "keyboard")):
        ctx, pg, st = make(b, w, h, dreams=seed.dreams(10))
        def f():
            pg.evaluate("document.getElementById('home-record-btn').click()"); settle(pg, 700); pg.fill("#dream-input", "Typing a dream with the keyboard open."); S(pg, "11_short_and_keyboard", "record_" + tag, w, h)
            pg.click("#interpret-btn"); pg.wait_for_selector(".feel-wheel"); settle(pg, 700); S(pg, "11_short_and_keyboard", "wheel_" + tag, w, h)
            pick_child(pg, "fear", 0, 0); pick_child(pg, "trust", 0, 0); S(pg, "11_short_and_keyboard", "wheel_selected_" + tag, w, h)
        step("extra " + tag, f)
        def g():
            pg.evaluate("document.querySelector('.bottom-tab-btn[data-tab=\"symbols\"], .side-nav-btn[data-tab=\"symbols\"]').click()"); settle(pg, 1200); S(pg, "11_short_and_keyboard", "loom_" + tag, w, h)
        step("extra loom " + tag, g); ctx.close()

if __name__ == "__main__":
    only = sys.argv[1:] 
    with sync_playwright() as p:
        b = p.chromium.launch()
        for (w, h) in VPS:
            if only and "%dx%d" % (w, h) not in only: continue
            step("flow %dx%d" % (w, h), lambda: flow(b, w, h))
        if not only or "extras" in only: extras(b)
        b.close()
    open(os.path.dirname(__file__) + "/capture_log.txt", "a").write("\n".join(LOG) + "\n")
    print(len([l for l in LOG if not l.startswith("FAILED")]), "shots;", [l for l in LOG if l.startswith("FAILED")])
