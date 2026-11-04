import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import capture as C
from capture import make, S, tab, settle, seed, VPS, sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    for (w, h) in VPS:
        ctx, pg, st = make(b, w, h, dreams=seed.dreams(30))
        try:
            tab(pg, "symbols"); settle(pg, 1200)
            pg.locator(".loom-graph-node--symbol").first.click(); settle(pg, 800)
            pg.click("#loom-preview-explore-btn"); settle(pg, 1500)
            S(pg, "07_loom_map", "element_detail", w, h); S(pg, "07_loom_map", "element_detail_full", w, h, True)
            pg.evaluate("(()=>{const t=document.getElementById('symbol-screen-tab-dreams')||[...document.querySelectorAll('#symbol-screen [role=tab]')][1];t&&t.click()})()"); settle(pg, 800); S(pg, "07_loom_map", "element_detail_related_dreams", w, h)
        except Exception as e: C.LOG.append("FAILED elem %dx%d %s" % (w, h, str(e).splitlines()[0][:100]))
        ctx.close()
    b.close()
print([l for l in C.LOG if l.startswith("FAILED")], len(C.LOG))
