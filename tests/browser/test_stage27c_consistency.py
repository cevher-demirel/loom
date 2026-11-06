"""Stage 27c -- 12px text floor, typographic dashes, consistent labels, chip-row scroll cue, no overflow."""
import re
import pathlib
import pytest

from tests.browser.harness import make
from tests.browser import seed
from tests.browser.test_stage27b_accessibility import HITJS, SCREENS, _dreams, _go

pytestmark = pytest.mark.browser
VIEWPORTS = [(320, 568), (375, 667), (390, 844), (430, 932), (768, 1024), (1280, 800)]
SRC = pathlib.Path(__file__).resolve().parents[2] / "index.html"
import os
if os.environ.get("LOOM_INDEX_HTML"):
    SRC = pathlib.Path(os.environ["LOOM_INDEX_HTML"])

SMALL_JS = """(function(){var out=[];var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);var n;
while(n=w.nextNode()){var t=n.nodeValue.trim();if(!t)continue;var p=n.parentElement;if(!p||p.closest('script,style,svg'))continue;
 var r=p.getBoundingClientRect();if(r.width<1||r.height<1)continue;var cs=getComputedStyle(p);if(cs.visibility==='hidden')continue;
 var fs=parseFloat(cs.fontSize);if(fs<11.95)out.push({t:t.slice(0,30),fs:fs,cls:String(p.className)});
 if(/(^|\\s)--(\\s|$)/.test(t))out.push({t:t.slice(0,30),dash:true})}
 return out})()"""
EXTRA = {"insights": ([("tab", "insights")], [])}


# ---- 1. 12px floor and no "--" in rendered copy -------------------------------------------------
@pytest.mark.parametrize("w,h", [(390, 844), (320, 568), (1280, 800)])
@pytest.mark.parametrize("screen", ["home", "journal", "map", "detail", "settings", "profile"])
def test_no_text_under_12px_and_no_double_hyphen_dashes(browser, w, h, screen):
    steps, _ = SCREENS[screen]
    ctx, page, st = make(browser, width=w, height=h, dreams=_dreams(8))
    page.wait_for_timeout(500)
    _go(page, steps)
    bad = page.evaluate(SMALL_JS)
    assert bad == [], bad
    assert st["errors"] == []
    ctx.close()


def _visible_source(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return "\n".join(re.sub(r"(?<![:\"'])//.*$", "", l) for l in text.split("\n"))


def test_source_has_no_double_hyphen_used_as_punctuation_in_copy():
    code = _visible_source(SRC.read_text())
    hits = [l.strip()[:100] for l in code.split("\n") if " -- " in l]
    assert hits == [], hits


def test_small_ui_labels_use_one_capitalisation_and_wording():
    src = SRC.read_text()
    for old in ["Reset Filters", "Clear All</button>", "View List</button>", ">Use Photo<", ">About You<", '"Show fewer"']:
        assert old not in src, old
    for new in ["Reset filters", "Clear all", "View list", "Use photo", "About you", '"Show less"', '"Show all emotions"']:
        assert new in src, new


# ---- 2. chip row: scrolls only when needed, and a clipped chip always shows there is more -------
CHIPS_JS = """(function(){var c=document.querySelector('.journal-filter-chips'),cr=c.getBoundingClientRect();
 var chips=[].slice.call(c.querySelectorAll('.journal-filter-chip')).map(function(e){var r=e.getBoundingClientRect();return {l:r.left-cr.left,r:r.right-cr.left,name:e.textContent.trim()}});
 return {cw:cr.width,sw:c.scrollWidth,cl:c.clientWidth,chips:chips}})()"""


@pytest.mark.parametrize("w,h", VIEWPORTS)
def test_chip_row_signals_hidden_chips_only_when_there_are_some(browser, w, h):
    ctx, page, st = make(browser, width=w, height=h, dreams=_dreams(8))
    page.wait_for_timeout(500)
    _go(page, SCREENS["journal"][0])
    m = page.evaluate(CHIPS_JS)
    assert len(m["chips"]) == 5 and all(c["name"] for c in m["chips"])
    if m["sw"] > m["cl"] + 1:                      # scrollable: the last chip must be visibly cut off
        clipped = [c for c in m["chips"] if c["r"] > m["cl"] + 6 and c["l"] < m["cl"] - 12]
        assert clipped, (w, m)
    else:                                          # everything fits: no chip may be cut
        assert all(c["r"] <= m["cl"] + 1 for c in m["chips"]), (w, m)
    ctx.close()


# ---- 3. touch targets / names / focus on the controls touched in 27c ---------------------------
def test_view_list_link_keeps_hit_area_name_and_focus_ring(browser):
    ctx, page, st = make(browser, width=320, height=568, dreams=_dreams(18) + [dict(d, id=100 + i) for i, d in enumerate(seed.dreams(10, seed=3))])
    page.wait_for_timeout(500)
    _go(page, SCREENS["map"][0])
    rs = page.evaluate(HITJS + "('#loom-graph-view-list-btn')")
    if rs:
        r = rs[0]
        assert r["name"] == "View list" and r["hit"]["h"] >= 43, r
        page.keyboard.press("Tab")
        page.evaluate("document.querySelector('#loom-graph-view-list-btn').focus({focusVisible:true})")
        assert page.evaluate("(function(){var cs=getComputedStyle(document.activeElement);return cs.outlineStyle!=='none'&&parseFloat(cs.outlineWidth)>=2})()")
    ctx.close()


@pytest.mark.parametrize("w,h", VIEWPORTS)
def test_no_horizontal_overflow_after_text_changes(browser, w, h):
    for screen in ["home", "journal", "map", "detail", "settings", "profile"]:
        ctx, page, st = make(browser, width=w, height=h, dreams=_dreams(8))
        page.wait_for_timeout(400)
        _go(page, SCREENS[screen][0])
        assert page.evaluate("document.documentElement.scrollWidth-document.documentElement.clientWidth") <= 0, (screen, w)
        ctx.close()
