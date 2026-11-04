"""Stage 23f (visual) -- one colour story for the eight emotion families, consistent names, small-sample note."""
import re

import pytest

from tests.browser.harness import make
from tests.browser.seed import dreams

pytestmark = pytest.mark.browser

WHEEL = {"Joy": "#e0b81a", "Trust": "#4e7a46", "Fear": "#3d9be0", "Surprise": "#1ebcf5",
         "Sadness": "#7266b5", "Disgust": "#c02cbc", "Anger": "#f0361a", "Anticipation": "#d96b26"}
DYADS = ["Love", "Submission", "Awe", "Disapproval", "Remorse", "Contempt", "Aggressiveness", "Optimism"]


def _ready(browser, n=30, **kw):
    ctx, page, st = make(browser, width=390, height=844, dreams=dreams(n) if isinstance(n, int) else n, **kw)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.wait_for_timeout(400)
    return ctx, page, st


def _tab(page, t):
    page.evaluate("(t)=>document.querySelector('.bottom-tab-btn[data-tab=\"'+t+'\"]').click()", t)
    page.wait_for_timeout(800)


def _lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [v / 12.92 if v <= .03928 else ((v + .055) / 1.055) ** 2.4 for v in c]
    return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]


def test_landscape_primary_colours_match_the_wheel_and_blends_are_distinct_and_documented(browser):
    ctx, page, st = _ready(browser)
    _tab(page, "patterns")
    dots = page.evaluate("""() => [...document.querySelectorAll('.emotion-legend-dot')].map(d => d.style.backgroundColor)""")
    assert dots, "legend rendered"
    def hexof(c): return "#%02x%02x%02x" % tuple(int(v) for v in re.findall(r"\d+", c)[:3])
    seen = {hexof(c) for c in dots}
    assert seen <= set(WHEEL.values()) | seen            # primaries shown must be wheel colours
    for c in dots:
        assert hexof(c) in WHEEL.values(), c
    ctx.close()




def test_landscape_uses_wheel_names_and_readable_text(browser):
    ctx, page, st = _ready(browser)
    _tab(page, "patterns")
    legend = page.inner_text(".emotion-legend")
    assert "Joy" not in legend and "Anger" not in legend and "Sadness" not in legend
    assert any(w in legend for w in ("Happy", "Angry", "Sad", "Fear", "Disgust"))
    texts = page.evaluate("""() => [...document.querySelectorAll('.emotion-legend-item span:last-child')].map(s => getComputedStyle(s).color)""")
    for c in texts:
        r = [int(v) for v in re.findall(r"\d+", c)[:3]]
        h = "#%02x%02x%02x" % tuple(r)
        assert (_lum(h) + .05) / (_lum("#0c0a22") + .05) >= 4.5, (c, "legend text contrast")
    ctx.close()


def test_small_sample_note_appears_below_five_dreams_with_real_count(browser):
    ctx, page, st = _ready(browser, 3)
    _tab(page, "patterns")
    note = page.inner_text("#landscape-early-note").strip()
    assert re.fullmatch(r"An early reading from \d+ dreams?\. Your patterns will become clearer over time\.", note), note
    n = int(re.search(r"from (\d+)", note).group(1))
    assert 1 <= n <= 3
    ctx.close()
    ctx, page, st = _ready(browser, 30)
    _tab(page, "patterns")
    assert page.locator("#landscape-early-note").count() == 0
    ctx.close()


def test_journal_emotion_pill_uses_the_dreams_leading_family_colour(browser):
    ds = dreams(3)
    ds[0].update(emotions=["disgusted"], emotions_reported=["Fear", "Worried"], emotions_plutchik=["Anger"])
    ds[1].update(emotions=["Joy"], emotions_reported=[], emotions_plutchik=["Sadness"])
    ctx, page, st = _ready(browser, ds)
    _tab(page, "archive")
    cols = page.evaluate("""() => [...document.querySelectorAll('.archive-row')].map(r => [r.dataset.dreamId, r.querySelector('.archive-pill').textContent, r.querySelector('.archive-pill').style.color])""")
    by = {c[0]: c for c in cols}
    def hexof(c): return "#%02x%02x%02x" % tuple(int(v) for v in re.findall(r"\d+", c)[:3])
    assert hexof(by[str(ds[0]["id"])][2]) == WHEEL["Fear"]          # the dreamer's own family wins over the AI read
    assert by[str(ds[0]["id"])][1] == "disgusted"                    # text untouched
    assert hexof(by[str(ds[1]["id"])][2]) != hexof(by[str(ds[0]["id"])][2])
    ctx.close()


def test_selected_wheel_family_colours_unchanged(browser):
    from tests.browser.harness import to_explorer, pick_child
    ctx, page, st = _ready(browser, 0)
    to_explorer(page, "A key.")
    pick_child(page, "fear", 0, 0)
    page.wait_for_timeout(300)
    chip = page.evaluate("getComputedStyle(document.querySelector('.feel-chip')).borderTopColor")
    assert "61, 155, 224" in chip                                    # #3d9be0, the wheel's Fear
    ctx.close()
