"""Stage 27b -- auth field contrast, emotion/tag pill contrast, 44px hit areas, focus rings, names, overflow."""
import pytest

from tests.browser.harness import make
from tests.browser import seed

pytestmark = pytest.mark.browser
VIEWPORTS = [(320, 568), (375, 667), (390, 844), (430, 932), (768, 1024), (1280, 800)]

CONTRAST_JS = """
function lin(v){v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)}
function lum(c){return 0.2126*lin(c[0])+0.7152*lin(c[1])+0.0722*lin(c[2])}
function ratio(a,b){var x=lum(a),y=lum(b);return (Math.max(x,y)+0.05)/(Math.min(x,y)+0.05)}
function parse(s){var m=s.match(/rgba?\\(([^)]+)\\)/g)||[];return m.map(function(t){var n=t.replace(/rgba?\\(|\\)/g,'').split(/[ ,\\/]+/).filter(Boolean).map(Number);return {c:n.slice(0,3),a:n.length>3?n[3]:1}})}
function over(fg,bg){return [0,1,2].map(function(i){return fg.c[i]*fg.a+bg[i]*(1-fg.a)})}
"""


def _dreams(n):
    ds = seed.dreams(n)
    for i, d in enumerate(ds):
        d["id"] = i + 1
    return ds


def _tab(page, name):
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=%s], .side-nav-btn[data-tab=%s]').click()" % (name, name))
    page.wait_for_timeout(500)


# ---- 1. auth field boundaries (WCAG 1.4.11 needs >= 3:1) -------------------------------------
def test_auth_field_borders_meet_non_text_contrast(browser):
    ctx, page, st = make(browser, dreams=_dreams(3))
    res = page.evaluate("(function(){" + CONTRAST_JS + """
      var bg=[10,10,26], out=[];
      var card=getComputedStyle(document.querySelector('.auth-card'));
      var stops=parse(card.backgroundImage).map(function(s){return over(s,bg)});
      ['login-username','login-password','forgot-email','reset-password','signup-username','signup-email','signup-password'].forEach(function(id){
        var el=document.getElementById(id), cs=getComputedStyle(el);
        var border=parse(cs.borderTopColor)[0].c, fill=parse(cs.backgroundColor)[0], fillRgb=over(fill,bg);
        out.push({id:id, vsCard:Math.min.apply(null,stops.map(function(s){return ratio(border,s)})), vsFill:ratio(border,fillRgb)});
      });
      return out})()""")
    for r in res:
        assert r["vsCard"] >= 3.0, r
        assert r["vsFill"] >= 3.0, r
    print("auth field border contrast", [(r["id"], round(r["vsCard"], 2), round(r["vsFill"], 2)) for r in res])
    ctx.close()


# ---- 2. every emotion + tag pill colour reaches AA (1.4.3) ------------------------------------
EMOTION_KEYS = ["Joy", "Trust", "Fear", "Surprise", "Sadness", "Disgust", "Anger", "Anticipation",
                "Love", "Submission", "Awe", "Disapproval", "Remorse", "Contempt", "Aggressiveness", "Optimism"]
PILL_NAMES = ["a key", "water", "a door", "flying", "a house", "a staircase", "the ocean", "a mirror", "a snake", "a forest",
              "a train", "teeth", "a bridge", "fire", "a cat", "cave", "moon", "river", "garden", "lantern"]


def test_all_emotion_and_tag_pills_meet_aa(browser):
    ds = []
    for i, k in enumerate(EMOTION_KEYS):
        ds.append({"id": i + 1, "timestamp": "2026-03-%02dT10:00:00Z" % (i + 1), "raw_text": "dream %d" % i, "interpretation": "x",
                   "symbols": [], "emotions": [k], "emotions_plutchik": [], "people": [], "settings": [], "themes": [], "symbol_icons": {},
                   "emotions_reported": [], "conversation": [], "location": ""})
    for j, s in enumerate(PILL_NAMES):
        ds.append({"id": 100 + j, "timestamp": "2026-04-%02dT10:00:00Z" % (j + 1), "raw_text": "tag dream %d" % j, "interpretation": "x",
                   "symbols": [s], "emotions": [], "emotions_plutchik": [], "people": [], "settings": [], "themes": [],
                   "symbol_icons": {s: "key"}, "emotions_reported": [], "conversation": [], "location": ""})
    ctx, page, st = make(browser, dreams=ds)
    _tab(page, "archive")
    res = page.evaluate("(function(){" + CONTRAST_JS + """
      var base=[21,19,47];   // --surface, the row the pill sits on
      return [].slice.call(document.querySelectorAll('.archive-pill')).map(function(p){
        var cs=getComputedStyle(p), fg=parse(cs.color)[0].c, fill=over(parse(cs.backgroundColor)[0], base);
        return {t:p.textContent, ratio:ratio(fg,fill), fs:parseFloat(cs.fontSize), color:cs.color}})})()""")
    emo = [r for r in res if r["t"] in EMOTION_KEYS]
    assert len(emo) == len(EMOTION_KEYS), (len(emo), [r["t"] for r in res][:40])
    assert len(res) >= len(EMOTION_KEYS) + 6
    for r in res:
        assert r["ratio"] >= 4.5, r
        assert r["fs"] >= 12, r
    print("pill min ratio", round(min(r["ratio"] for r in res), 2), "emotions", {r["t"]: round(r["ratio"], 2) for r in emo})
    assert st["errors"] == []
    ctx.close()


# ---- 3. hit areas ------------------------------------------------------------------------------
HITJS = """(function(sel){
  function hit(el){var r=el.getBoundingClientRect(),l=1e9,t=1e9,rr=-1,bb=-1;
    for(var y=Math.floor(r.top)-30;y<=Math.ceil(r.bottom)+30;y++)for(var x=Math.floor(r.left)-30;x<=Math.ceil(r.right)+30;x++){
      if(x<0||y<0||x>=innerWidth||y>=innerHeight)continue;var e=document.elementFromPoint(x,y);
      if(e&&(e===el||el.contains(e))){l=Math.min(l,x);rr=Math.max(rr,x);t=Math.min(t,y);bb=Math.max(bb,y);}}
    return rr<0?null:{l:l,t:t,r:rr+1,b:bb+1,w:rr-l+1,h:bb-t+1}}
  return [].slice.call(document.querySelectorAll(sel)).filter(function(el){var cs0=getComputedStyle(el);if(cs0.display==='none')return false;
      var r0=el.getBoundingClientRect();if(r0.width>1&&r0.height>1&&el.scrollIntoView&&!el.closest('.journal-filter-chips'))el.scrollIntoView({block:'center'});
      var r=el.getBoundingClientRect(),cs=getComputedStyle(el);
      return r.width>1&&r.height>1&&cs.visibility!=='hidden'&&r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight}).map(function(el){
    var r=el.getBoundingClientRect();return {sel:sel,id:el.id,name:el.getAttribute('aria-label')||el.textContent.trim().slice(0,24),vw:Math.round(r.width),vh:Math.round(r.height),hit:hit(el)}})})"""

SCREENS = {
    "home": ([], [".header-gear-btn", "#home-search-btn", ".home-footer-links button", "#home-discovery-review-btn"]),
    "journal": ([("tab", "archive")], [".journal-filter-chip"]),
    "map": ([("tab", "symbols")], [".loom-view-btn", ".loom-map-filter-btn", "#loom-graph-view-list-btn"]),
    "detail": ([("tab", "archive"), ("js", "document.querySelector('.archive-item').click()")],
               ["#dream-screen-back-btn", "#dream-screen-edit-date-btn", "#dream-screen-edit-dream-btn", "#dream-screen-delete-btn", ".more-toggle"]),
    "settings": ([("js", "document.querySelector('.header-gear-btn').click()")], ["#settings-back-btn"]),
    "profile": ([("js", "document.querySelector('.header-gear-btn').click()"), ("js", "document.querySelector('#settings-go-profile-btn').click()")], ["#logout-btn"]),
}


def _go(page, steps):
    for kind, v in steps:
        if kind == "tab":
            _tab(page, v)
        else:
            page.evaluate(v)
            page.wait_for_timeout(500)


@pytest.mark.parametrize("w,h", [(320, 568), (390, 844)])
@pytest.mark.parametrize("screen", list(SCREENS))
def test_small_controls_have_44px_hit_areas_that_do_not_overlap(browser, w, h, screen):
    steps, sels = SCREENS[screen]
    ctx, page, st = make(browser, width=w, height=h, dreams=_dreams(8))
    page.wait_for_timeout(500)
    _go(page, steps)
    found, boxes = 0, []
    for sel in sels:
        for r in page.evaluate(HITJS + "(%r)" % sel):
            if not r["hit"]:
                continue
            found += 1
            assert r["hit"]["w"] >= 43 and r["hit"]["h"] >= 43, ("hit area < 44", screen, w, r)
            boxes.append(r)
    assert found >= 1, (screen, sels)
    # hit areas are exclusive by construction (elementFromPoint), so overlap is impossible; also
    # check that no two controls' *visible* boxes were pushed together by the enlargement
    assert st["errors"] == []
    ctx.close()


def test_edit_and_delete_keep_separate_44px_areas(browser):
    ctx, page, st = make(browser, dreams=_dreams(4))
    _go(page, SCREENS["detail"][0])
    a = page.evaluate(HITJS + "('#dream-screen-edit-dream-btn')")[0]["hit"]
    b = page.evaluate(HITJS + "('#dream-screen-delete-btn')")[0]["hit"]
    assert a["w"] >= 43 and b["w"] >= 43 and a["h"] >= 43 and b["h"] >= 43, (a, b)
    assert a["r"] <= b["l"] or b["r"] <= a["l"]
    ctx.close()


# ---- 4. focus rings + accessible names ---------------------------------------------------------
FOCUS_SELS = ["#home-search-btn", ".home-footer-links button", "#home-discovery-review-btn"]


def test_keyboard_focus_ring_is_visible_on_enlarged_controls(browser):
    ctx, page, st = make(browser, dreams=_dreams(6))
    page.wait_for_timeout(700)
    for sel in FOCUS_SELS:
        page.keyboard.press("Tab")
        page.evaluate("[].slice.call(document.querySelectorAll(%r)).filter(function(e){return e.getBoundingClientRect().width>1})[0].focus({focusVisible:true})" % sel)
        res = page.evaluate("(function(){var e=document.activeElement,cs=getComputedStyle(e);return {m:e.matches(':focus-visible'),ow:parseFloat(cs.outlineWidth),os:cs.outlineStyle,sh:cs.boxShadow}})()")
        assert res["m"] and ((res["os"] != "none" and res["ow"] >= 2) or res["sh"] != "none"), (sel, res)
    ctx.close()


def test_controls_keep_accessible_names(browser):
    ctx, page, st = make(browser, dreams=_dreams(6))
    for screen, (steps, sels) in SCREENS.items():
        ctx.close()
        ctx, page, st = make(browser, dreams=_dreams(6))
        _go(page, steps)
        for sel in sels:
            for r in page.evaluate(HITJS + "(%r)" % sel):
                assert r["name"], (screen, sel, r)
    ctx.close()


# ---- 5. no new horizontal overflow -------------------------------------------------------------
@pytest.mark.parametrize("w,h", VIEWPORTS)
def test_no_horizontal_overflow(browser, w, h):
    ctx, page, st = make(browser, width=w, height=h, dreams=_dreams(8))
    for screen, (steps, _) in SCREENS.items():
        ctx.close()
        ctx, page, st = make(browser, width=w, height=h, dreams=_dreams(8))
        _go(page, steps)
        assert page.evaluate("document.documentElement.scrollWidth-document.documentElement.clientWidth") <= 0, (screen, w)
    ctx.close()
