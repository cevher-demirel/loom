"""Stage 23b -- touch targets (>=44px incl. invisible padding, no overlap), 12px text, nav contrast, keyboard."""
import pytest

from tests.browser.harness import make, pick_child, to_explorer

pytestmark = pytest.mark.browser

WIDTHS = [(320, 568), (375, 667), (390, 844), (430, 932)]

# (selector, screen) -- the controls named by the Stage 23 brief
TARGETS = {
    "home": ["#home-search-btn", "#home-link-settings", "#home-link-privacy", "#home-link-export", ".bottom-tab-btn[data-tab=archive]"],
    "journal": ["#journal-head-back-btn", "#journal-head-add-btn", ".header-gear-btn", ".journal-filter-chip:nth-child(2)", ".journal-filter-chip:nth-child(3)"],
    "map": ["#loom-map-filter-btn", "#loom-view-network-btn", "#loom-view-timeline-btn", "#loom-view-list-btn", "#loom-graph-zoom-in", "#loom-graph-zoom-out", "#loom-graph-reset"],
    "insights": [],
    "profile": ["#settings-back-btn"],
}

HIT_JS = """
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return {missing: true};
  el.scrollIntoView({block: 'center'});
  const r = el.getBoundingClientRect();
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  const owns = (x, y) => { const t = document.elementFromPoint(x, y); return !!t && (t === el || el.contains(t)); };
  // The element must own a 44x44 box around its centre (clamped to the viewport).
  const half = 21.5, W = innerWidth, H = innerHeight;
  const pts = [[cx - half, cy], [cx + half, cy], [cx, cy - half], [cx, cy + half]]
    .map(([x, y]) => [Math.min(Math.max(x, 1), W - 1), Math.min(Math.max(y, 1), H - 1)]);
  // Elements wider/taller than 44 own their own extent; only test the short axis.
  const need = [];
  if (r.width < 44) { need.push(pts[0], pts[1]); }
  if (r.height < 44) { need.push(pts[2], pts[3]); }
  return {w: r.width, h: r.height, fails: need.filter(([x, y]) => !owns(x, y)).length, tested: need.length};
}
"""


def _open(page, tab):
    page.evaluate("(t)=>document.querySelector('.bottom-tab-btn[data-tab=\"'+t+'\"]').click()", tab)
    page.wait_for_timeout(700)


def _check(page, sels):
    bad = []
    for s in sels:
        r = page.evaluate(HIT_JS, s)
        if r.get("missing"):
            bad.append((s, "missing")); continue
        if r["fails"]:
            bad.append((s, r))
    assert not bad, bad


@pytest.mark.parametrize("w,h", WIDTHS)
def test_touch_targets_are_44px_without_overlap(browser, w, h):
    from tests.browser.seed import dreams
    ctx, page, st = make(browser, width=w, height=h, dreams=dreams(30))
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.wait_for_timeout(400)
    _check(page, TARGETS["home"])
    _open(page, "archive")
    _check(page, TARGETS["journal"])
    _open(page, "symbols")
    _check(page, TARGETS["map"])
    page.evaluate("document.querySelector('.header-gear-btn').click()")
    page.wait_for_timeout(700)
    _check(page, TARGETS["profile"])
    ctx.close()


@pytest.mark.parametrize("w,h", WIDTHS)
def test_visible_text_is_at_least_12px_and_nav_contrast(browser, w, h):
    from tests.browser.seed import dreams
    ctx, page, st = make(browser, width=w, height=h, dreams=dreams(30))
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    js = """() => [...document.querySelectorAll('body *')].filter(e => {
        const r = e.getBoundingClientRect(), s = getComputedStyle(e);
        if (!(r.width > 0 && r.height > 0) || s.visibility === 'hidden' || s.display === 'none') return false;
        if (e.closest('svg') || e.closest('#app-splash')) return false;
        return [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()) && parseFloat(s.fontSize) < 12;
      }).map(e => e.className + ':' + getComputedStyle(e).fontSize).slice(0, 8)"""
    for tab in ("home", "archive", "symbols", "patterns"):
        _open(page, tab)
        assert page.evaluate(js) == [], (tab, page.evaluate(js))
    lum = """() => { const l = c => { c = c.map(v => { v/=255; return v<=.03928? v/12.92 : Math.pow((v+.055)/1.055,2.4)}); return .2126*c[0]+.7152*c[1]+.0722*c[2]; };
      const p = s => s.match(/[\\d.]+/g).slice(0,3).map(Number);
      const out = {};
      document.querySelectorAll('.bottom-tab-btn').forEach(b => { const sel = b.getAttribute('aria-selected') === 'true';
        const fg = l(p(getComputedStyle(b).color)); const bg = l([14,12,40]);
        out[sel ? 'selected' : 'idle'] = Math.min(out[sel ? 'selected':'idle'] || 99, (Math.max(fg,bg)+.05)/(Math.min(fg,bg)+.05)); });
      return out; }"""
    r = page.evaluate(lum)
    assert r["idle"] >= 4.5 and r["selected"] >= 4.5, r
    ctx.close()


def test_changed_controls_are_keyboard_operable_with_visible_focus(browser):
    from tests.browser.seed import dreams
    ctx, page, st = make(browser, width=390, height=844, dreams=dreams(30))
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    _open(page, "symbols")
    page.focus("#loom-view-list-btn")
    outline = page.evaluate("getComputedStyle(document.activeElement).outlineStyle")
    assert outline != "none"
    page.keyboard.press("Enter")
    page.wait_for_timeout(400)
    assert page.evaluate("document.getElementById('loom-view-list-btn').classList.contains('loom-view-btn--active')")
    page.focus("#loom-graph-zoom-in") if page.locator("#loom-graph-zoom-in").is_visible() else None
    page.focus("#loom-map-filter-btn")
    page.keyboard.press("Enter")
    page.wait_for_timeout(500)
    assert page.locator("#loom-filters-sheet").is_visible()
    _check(page, ["#loom-filters-close-btn"])                                  # dialog close is a 44px target
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    assert page.evaluate("document.activeElement && document.activeElement.id") == "loom-map-filter-btn"   # focus restored
    ctx.close()


def test_reduced_motion_unaffected(browser):
    ctx, page, st = make(browser, width=390, height=844, reduced=True)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    _open(page, "archive")
    _check(page, ["#journal-head-back-btn"])
    ctx.close()
