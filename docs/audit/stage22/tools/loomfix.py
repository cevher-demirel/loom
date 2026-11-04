import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import capture as C
from capture import make, S, tab, settle, seed, VPS, sync_playwright
def sub(b, w, h, name, fn):
    ctx, pg, st = make(b, w, h, dreams=seed.dreams(30))
    try:
        tab(pg, "symbols"); settle(pg, 1200); fn(pg)
        S(pg, "07_loom_map", name, w, h)
        if name == "list": S(pg, "07_loom_map", "list_full", w, h, True)
    except Exception as e: C.LOG.append("FAILED %s %dx%d: %s" % (name, w, h, str(e).splitlines()[0][:100]))
    ctx.close()
def conn(pg):
    pg.locator(".loom-graph-node--symbol").first.click(); settle(pg, 900)
    pg.evaluate("document.querySelector('#loom-preview-connected-grid button').click()"); settle(pg, 900)
def filt(pg): pg.click("#loom-map-filter-btn"); settle(pg, 900)
def tl(pg): pg.click("#loom-view-timeline-btn"); settle(pg, 900)
def lst(pg): pg.click("#loom-view-list-btn"); settle(pg, 900)
def tl_detail(pg):
    pg.click("#loom-view-timeline-btn"); settle(pg, 600); pg.locator("#loom-timeline-picker-list button").first.click(); settle(pg, 900)
with sync_playwright() as p:
    b = p.chromium.launch()
    for (w, h) in VPS:
        for n, f in (("selected_connection", conn), ("filters_sheet", filt), ("timeline_picker", tl), ("timeline_element_detail", tl_detail), ("list", lst)):
            sub(b, w, h, n, f)
    b.close()
print([l for l in C.LOG if l.startswith("FAILED")], len(C.LOG))
