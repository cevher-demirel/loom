"""Stage 31 -- immersive Loom Map: full-screen network, Map-only artwork, touch gestures,
and every existing Map function still reachable (real behaviour, mocked backend)."""
import pytest

from tests.browser.harness import make, map_view
from tests.browser.seed import dreams
from tests.browser.test_stage27a_map_clarity import data

pytestmark = pytest.mark.browser
PHONES = [(375, 667), (390, 844), (430, 932), (360, 800), (320, 568)]
T = "document.getElementById('loom-graph-stage').style.transform"


def _map(browser, w=390, h=844, ds=None):
    ctx, page, st = make(browser, width=w, height=h, dreams=data() if ds is None else ds)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=symbols], .side-nav-btn[data-tab=symbols]').click()")
    page.evaluate("document.fonts && document.fonts.ready")
    page.wait_for_timeout(800)
    return ctx, page, st


def _center(page, sel, i=0):
    b = page.locator(sel).nth(i).bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


PINCH = """(async ([x1, x2, y, d]) => { var w=document.getElementById('loom-graph-wrap');
  function ev(t,id,x,y){ w.dispatchEvent(new PointerEvent(t,{pointerId:id,pointerType:'touch',clientX:x,clientY:y,bubbles:true,isPrimary:id===1})); }
  ev('pointerdown',1,x1,y); ev('pointerdown',2,x2,y);
  for (var i=1;i<=8;i++){ ev('pointermove',1,x1-i*d,y); ev('pointermove',2,x2+i*d,y); await new Promise(r=>setTimeout(r,16)); }
  ev('pointerup',1,x1-8*d,y); ev('pointerup',2,x2+8*d,y); })"""


@pytest.mark.parametrize("w,h", PHONES + [(1280, 800), (844, 390)])
def test_map_fills_the_screen_between_top_and_nav_with_every_node_inside(browser, w, h):
    ctx, page, st = _map(browser, w, h)
    r = page.evaluate("""(() => { var l=document.getElementById('loom-network-view').getBoundingClientRect(),
        n=document.getElementById('bottom-tabs-nav'), nr=n.getBoundingClientRect(), side=document.querySelector('.side-nav');
        return {top:l.top, bottom:l.bottom, left:l.left, right:l.right, navTop: n.offsetHeight ? nr.top : innerHeight,
                sideW: side && side.offsetWidth ? side.getBoundingClientRect().right : 0,
                nodes:[...document.querySelectorAll('.loom-graph-node')].map(b => { var c=b.getBoundingClientRect(); return [c.left,c.top,c.right,c.bottom]; }),
                scrollH: document.documentElement.scrollHeight}; })()""")
    assert r["top"] == 0 and abs(r["bottom"] - r["navTop"]) <= 1           # full height, never under the nav
    assert abs(r["left"] - r["sideW"]) <= 1 and abs(r["right"] - w) <= 1   # full width (beside the desktop sidebar)
    assert len(r["nodes"]) == 13                                           # You + 12
    for (l, t, rr, b) in r["nodes"]:
        assert l >= r["left"] - 0.5 and rr <= r["right"] + 0.5 and t >= 0 and b <= r["navTop"] + 0.5, (l, t, rr, b)
    assert r["scrollH"] <= h + 1                                           # nothing to scroll behind the map
    assert st["errors"] == []
    ctx.close()


@pytest.mark.parametrize("w,h", [(390, 844), (320, 568)])
def test_nodes_are_large_and_readable(browser, w, h):
    ctx, page, st = _map(browser, w, h)
    r = page.evaluate("""[...document.querySelectorAll('.loom-graph-node--symbol')].map(b => {
        var c=b.querySelector('.loom-graph-node-circle').getBoundingClientRect(), l=b.querySelector('.loom-graph-node-label'),
            s=l.getBoundingClientRect().height / l.offsetHeight;
        return {d:c.width, fs:parseFloat(getComputedStyle(l).fontSize)*s}; })""")
    you = page.locator("#loom-graph-you-btn").bounding_box()
    for x in r:
        assert x["d"] >= 58 and x["fs"] >= 11, x                           # old nodes were 61px circles with ~11px labels below
    assert you["width"] >= 64
    ctx.close()


def test_spokes_never_pass_behind_another_node(browser):
    ctx, page, st = _map(browser, 390, 844, ds=dreams(30))
    bad = page.evaluate("""(() => { var svg=document.getElementById('loom-graph-edges-svg'), m=svg.getScreenCTM(), out=[];
      var circles=[...document.querySelectorAll('.loom-graph-node--symbol')].map(b => { var r=b.querySelector('.loom-graph-node-circle').getBoundingClientRect();
        return {k:b.dataset.catKey, x:r.left+r.width/2, y:r.top+r.height/2, r:r.width/2}; });
      function pt(x,y){ var p=svg.createSVGPoint(); p.x=x; p.y=y; return p.matrixTransform(m); }
      document.querySelectorAll('.loom-graph-edge-hub:not(.loom-graph-edge-glow)').forEach(l => {
        var a=pt(+l.getAttribute('x1'),+l.getAttribute('y1')), b=pt(+l.getAttribute('x2'),+l.getAttribute('y2'));
        circles.forEach(c => { if (c.k === l.dataset.catKey) return;
          var dx=b.x-a.x, dy=b.y-a.y, t=Math.max(0,Math.min(1,((c.x-a.x)*dx+(c.y-a.y)*dy)/(dx*dx+dy*dy)));
          if (Math.hypot(c.x-a.x-t*dx, c.y-a.y-t*dy) < c.r - 1) out.push([l.dataset.catKey, c.k]); }); });
      return out; })()""")
    assert bad == []
    ctx.close()


@pytest.mark.parametrize("ds_name", ["27a", "seed30", "seed120"])
def test_distance_from_you_still_means_frequency(browser, ds_name):
    ds = {"27a": data(), "seed30": dreams(30), "seed120": dreams(120)}[ds_name]
    ctx, page, st = _map(browser, 390, 844, ds=ds)
    r = page.evaluate("""(() => { var st=document.getElementById('loom-graph-stage'), W=parseFloat(st.style.width), H=parseFloat(st.style.height);
      return [...document.querySelectorAll('.loom-graph-node--symbol')].map(b => { var x=(parseFloat(b.style.left)-50)/100*W, y=(parseFloat(b.style.top)-50)/100*H;
        return [+b.dataset.count, Math.hypot(x, y / (H / W))]; }); })()""")
    for c1, d1 in r:
        for c2, d2 in r:
            if c1 > c2:
                assert d1 <= d2 + 0.5, (c1, d1, c2, d2)                   # more frequent is never farther from You
    ctx.close()


def test_background_artwork_is_map_only_and_never_intercepts_touches(browser):
    ctx, page, st = _map(browser, 390, 844)
    bg = page.evaluate("(() => { var e=document.querySelector('.loom-map-bg'), cs=getComputedStyle(e); return {img:cs.backgroundImage, size:cs.backgroundSize, pos:cs.backgroundPosition, pe:cs.pointerEvents, vis:e.offsetWidth>0}; })()")
    assert "assets/map/loom-map-bg.webp" in bg["img"] and "gradient" in bg["img"]   # real artwork + dark gradient fallback
    assert "cover" in bg["size"] and bg["pe"] == "none" and bg["vis"]
    size = page.evaluate("new Promise(r => { var i=new Image(); i.onload=() => r([i.naturalWidth, i.naturalHeight]); i.onerror=() => r(null); i.src='assets/map/loom-map-bg.webp'; })")
    assert size == [941, 1672]                                             # the approved artwork, original size, undistorted
    # empty space on the map belongs to the gesture surface, not the artwork
    hit = page.evaluate("(() => { var e=document.elementFromPoint(12, 300); return !!e.closest('#loom-graph-wrap'); })()")
    assert hit
    for tab in ["home", "archive", "patterns"]:
        page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=%s]').click()" % tab)
        page.wait_for_timeout(300)
        assert page.locator(".loom-map-bg").is_hidden()
        assert page.locator("#app-header").is_visible() or tab == "home"
    ctx.close()


def test_tap_opens_node_and_drag_does_not(browser):
    ctx, page, st = _map(browser, 390, 844)
    x, y = _center(page, ".loom-graph-node--symbol", 0)
    page.touchscreen.tap(x, y)
    page.wait_for_timeout(300)
    assert page.locator("#loom-preview-sheet").is_visible()
    page.click("#loom-preview-node-close-btn"); page.wait_for_timeout(200)
    before = page.evaluate(T)
    page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x + 50, y + 30, steps=8); page.mouse.up()
    page.wait_for_timeout(300)
    assert page.locator("#loom-preview-sheet").is_hidden()                 # dragging from a node never opens it
    assert page.evaluate(T) != before                                      # ... it pans the network instead
    x2, y2 = _center(page, ".loom-graph-node--symbol", 3)
    page.mouse.click(x2, y2); page.wait_for_timeout(300)                   # the very next real tap still works
    assert page.locator("#loom-preview-sheet").is_visible()
    assert st["errors"] == []
    ctx.close()


def test_pinch_zooms_around_the_fingers_within_limits(browser):
    ctx, page, st = _map(browser, 390, 844)
    fit = page.evaluate("parseFloat(%s.match(/scale\\(([^)]+)/)[1])" % T)
    page.evaluate(PINCH, [160, 230, 400, 6])                               # spread: zoom in
    s1 = page.evaluate("parseFloat(%s.match(/scale\\(([^)]+)/)[1])" % T)
    assert s1 > fit * 1.5
    assert page.locator("#loom-preview-sheet").is_hidden()                 # a pinch never opens a node
    page.evaluate(PINCH, [100, 300, 400, 30])                              # huge spread: clamped at the max
    assert page.evaluate("parseFloat(%s.match(/scale\\(([^)]+)/)[1])" % T) <= max(2.4, fit * 1.6) + 1e-6
    page.evaluate(PINCH, [60, 330, 400, -16])                              # pinch in hard: back to the framed view
    assert abs(page.evaluate("parseFloat(%s.match(/scale\\(([^)]+)/)[1])" % T) - fit) < 1e-6
    assert page.evaluate(T).startswith("translate(0px, 0px)")              # ...and centered again
    assert st["errors"] == []
    ctx.close()


def test_mouse_wheel_zooms_on_desktop(browser):
    ctx, page, st = _map(browser, 1280, 800)
    fit = page.evaluate("parseFloat(%s.match(/scale\\(([^)]+)/)[1])" % T)
    page.mouse.move(760, 400)
    for _ in range(5):
        page.mouse.wheel(0, -120)
    page.wait_for_timeout(200)
    assert page.evaluate("parseFloat(%s.match(/scale\\(([^)]+)/)[1])" % T) > fit
    ctx.close()


def test_tapping_a_spoke_opens_that_elements_preview(browser):
    ctx, page, st = _map(browser, 390, 844)
    key, pt = page.evaluate("""(() => { var svg=document.getElementById('loom-graph-edges-svg'), l=svg.querySelector('.loom-graph-edge-hit--hub'), m=svg.getScreenCTM();
      var p=svg.createSVGPoint(); p.x=(+l.getAttribute('x1') + +l.getAttribute('x2'))/2; p.y=(+l.getAttribute('y1') + +l.getAttribute('y2'))/2; p=p.matrixTransform(m);
      return [l.dataset.catKey, [p.x, p.y]]; })()""")
    page.mouse.click(pt[0], pt[1]); page.wait_for_timeout(300)
    assert page.locator("#loom-preview-sheet").is_visible()
    assert page.locator(".loom-graph-node--selected").get_attribute("data-cat-key") == key
    ctx.close()


def test_you_reaches_filters_timeline_list_and_recenter(browser):
    ctx, page, st = _map(browser, 390, 844, ds=dreams(30))
    page.mouse.move(195, 420); page.mouse.down(); page.mouse.move(260, 470, steps=6); page.mouse.up()
    assert not page.evaluate(T).startswith("translate(0px, 0px)")
    map_view(page, "recenter")
    assert page.evaluate(T).startswith("translate(0px, 0px)")
    map_view(page, "filters")
    assert page.locator("#loom-filters-sheet").is_visible()
    page.locator('input[data-filter-category="emotion"]').evaluate("e => e.click()")
    page.click("#loom-filters-apply-btn"); page.wait_for_timeout(500)
    assert page.locator(".loom-graph-node--symbol[data-category=emotion]").count() == 0
    assert "filters on" in page.get_attribute("#loom-graph-you-btn", "aria-label")
    map_view(page, "list")
    assert page.locator("#loom-list-view").is_visible() and page.locator(".loom-view-toggle").first.is_visible()
    map_view(page, "network")
    assert page.locator("#loom-graph-you-btn").is_visible() and page.locator(".loom-view-toggle").first.is_hidden()
    map_view(page, "timeline")
    assert page.locator("#loom-timeline-view").is_visible()
    assert st["errors"] == []
    ctx.close()


def test_load_error_banner_with_retry_floats_above_the_map(browser):
    ctx, page, st = make(browser, width=390, height=844, dreams=data(), dreams_script=["500"])
    page.wait_for_selector("#dreams-load-banner:not([hidden])", timeout=6000)
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=symbols]').click()"); page.wait_for_timeout(500)
    b = page.locator("#dreams-load-retry-btn")
    assert b.is_visible()
    x, y = _center(page, "#dreams-load-retry-btn")
    assert page.evaluate("(([x,y]) => document.elementFromPoint(x,y).id)", [x, y]) == "dreams-load-retry-btn"
    b.click()
    page.wait_for_function("document.querySelectorAll('.loom-graph-node--symbol').length > 0", timeout=8000)
    ctx.close()


def test_empty_map_keeps_its_empty_state_on_the_artwork(browser):
    ctx, page, st = _map(browser, 390, 844, ds=[])
    assert page.locator("#loom-graph-empty-note").is_visible() and page.locator(".loom-map-bg").is_visible()
    page.click("#loom-graph-empty-record-btn"); page.wait_for_timeout(400)
    assert page.locator("#dream-input").is_visible()
    ctx.close()
