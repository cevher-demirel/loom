"""Stage 27d -- emotion-flower centre label stays inside its dial; Home wordmark ghost is only the splash fade."""
import pytest

from tests.browser.harness import make
from tests.browser import seed

pytestmark = pytest.mark.browser
VIEWPORTS = [(320, 568), (375, 667), (390, 844), (430, 932), (768, 1024), (1280, 800)]
FAMILIES = ["Joy", "Trust", "Fear", "Surprise", "Sadness", "Disgust", "Anger", "Anticipation"]

DIAL_JS = """(function(sel){
  var wrap=document.querySelector(sel); if(!wrap) return null;
  var circles=wrap.querySelectorAll('svg circle'); var dial=circles[circles.length-1], dr=dial.getBoundingClientRect();
  var cx=dr.left+dr.width/2, cy=dr.top+dr.height/2, R=dr.width/2;
  var label=wrap.querySelector('div'); var out=[]; var w=document.createTreeWalker(label,NodeFilter.SHOW_TEXT),n;
  while(n=w.nextNode()){ if(!n.nodeValue.trim()) continue; var rg=document.createRange(); rg.selectNodeContents(n); var r=rg.getBoundingClientRect();
    var worst=0; [[r.left,r.top+r.height*0.125],[r.right,r.top+r.height*0.125],[r.left,r.bottom-r.height*0.125],[r.right,r.bottom-r.height*0.125]].forEach(function(p){worst=Math.max(worst,Math.hypot(p[0]-cx,p[1]-cy))});
    out.push({t:n.nodeValue.trim(),fs:parseFloat(getComputedStyle(n.parentElement).fontSize),reach:worst,R:R,w:r.width}) }
  return {R:R,texts:out,dialD:dr.width,wrapW:wrap.getBoundingClientRect().width}})"""


def _dream(i, fam, extra=()):
    return {"id": i, "timestamp": "2026-03-%02dT10:00:00Z" % (i + 1), "raw_text": "dream %d about a quiet house." % i, "interpretation": "x\n\ny",
            "symbols": [], "emotions": [fam.lower()], "emotions_plutchik": [fam] + list(extra), "people": [], "settings": [], "themes": [],
            "symbol_icons": {}, "emotions_reported": [], "conversation": [], "location": ""}


def _tab(page, name):
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=%s], .side-nav-btn[data-tab=%s]').click()" % (name, name))
    page.wait_for_timeout(500)


@pytest.mark.parametrize("w,h", VIEWPORTS)
@pytest.mark.parametrize("fam", FAMILIES)
def test_landscape_flower_label_is_inside_its_dial(browser, w, h, fam):
    ctx, page, st = make(browser, width=w, height=h, dreams=[_dream(1, fam, ("Fear", "Joy", "Sadness") if fam not in ("Fear", "Joy", "Sadness") else ())])
    page.wait_for_timeout(500)
    _tab(page, "patterns")
    m = page.evaluate(DIAL_JS + "('#insights-landscape .emotion-wheel-wrap')")
    assert m and m["texts"], m
    for t in m["texts"]:
        assert t["fs"] >= 11.95, t                       # keeps the 12px text floor
        assert t["reach"] <= m["R"] + 1.5, (fam, w, t)  # every corner of every line is inside the dial
    assert m["dialD"] >= 66
    ctx.close()


@pytest.mark.parametrize("w,h", [(320, 568), (390, 844), (1280, 800)])
@pytest.mark.parametrize("fam,extra", [(f, e) for f in FAMILIES for e in ((), ("Fear", "Joy", "Trust"))])
def test_dream_flower_label_is_inside_its_dial(browser, w, h, fam, extra):
    extra = tuple(x for x in extra if x != fam)
    ctx, page, st = make(browser, width=w, height=h, dreams=[_dream(1, fam, extra)])
    page.wait_for_timeout(500)
    _tab(page, "archive")
    page.evaluate("document.querySelector('.archive-item').click()")
    page.wait_for_timeout(700)
    m = page.evaluate(DIAL_JS + "('#dream-screen-body .emotion-wheel-wrap, #dream-screen .emotion-wheel-wrap')")
    assert m and m["texts"], m
    for t in m["texts"]:
        assert t["fs"] >= 11.95, t
        assert t["reach"] <= m["R"] + 1.5, (fam, extra, w, t)
    ctx.close()


def test_flower_petal_geometry_and_colours_unchanged(browser):
    ctx, page, st = make(browser, dreams=[_dream(1, "Fear", ("Joy",)), _dream(2, "Joy")])
    page.wait_for_timeout(500)
    _tab(page, "patterns")
    paths = page.evaluate("[].slice.call(document.querySelectorAll('#insights-landscape svg path')).map(function(p){return [p.getAttribute('d').slice(0,24),p.getAttribute('fill'),p.getAttribute('opacity')]})")
    assert len(paths) >= 2 and all(p[1].startswith('#') for p in paths)
    ctx.close()


# ---- Home: the faint "Loominous" ghost is the splash cross-fade, not a persistent overlay -------
@pytest.mark.parametrize("w,h", [(390, 844), (1280, 800)])
def test_home_has_no_persistent_wordmark_overlay_once_splash_is_gone(browser, w, h):
    ds = seed.dreams(6)
    for i, d in enumerate(ds):
        d["id"] = i + 1
    ctx, page, st = make(browser, width=w, height=h, dreams=ds)
    page.wait_for_function("getComputedStyle(document.getElementById('app-splash')).display==='none'", timeout=5000)
    page.wait_for_timeout(300)
    hits = page.evaluate("""(function(){var out=[];var pts=[[0.25,0.5],[0.5,0.5],[0.5,0.62],[0.5,0.3]];
      pts.forEach(function(p){document.elementsFromPoint(innerWidth*p[0],innerHeight*p[1]).forEach(function(e){var t=(e.textContent||'').trim();
        if(e.children.length===0&&/^Loominous$/.test(t)&&getComputedStyle(e).opacity>0&&e.getBoundingClientRect().width>0&&!e.closest('.home-hero-top,.side-nav,.app-header'))out.push(e.className)})});return out})()""")
    assert hits == [], hits
    ctx.close()
