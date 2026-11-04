"""Stage 23f-2 -- Landscape prioritises the dreamer's selected emotions; deterministic before/after."""
import re

import pytest

from tests.browser.harness import make
from tests.browser.seed import dreams

pytestmark = pytest.mark.browser


def _d(i, reported, plutchik):
    base = dreams(1)[0]
    base.update(id=i, emotions_reported=reported, emotions_plutchik=plutchik, timestamp="2026-0%d-10T10:00:00Z" % (i % 9 + 1))
    return base


DATASET = [
    _d(1, ["Fear", "Cautious"], ["Anger"]),            # user Fear beats AI Anger
    _d(2, [], ["Joy"]),                               # AI only
    _d(3, ["Sadness", "Joy", "Hopeful"], ["Trust"]),  # user Sadness + Joy
    _d(4, ["Awe", "Contempt"], ["Disgust"]),          # leaf names that collide with blends: ignored -> AI
    _d(5, ["Fear", "Awe"], []),                       # Fear only; "Awe" (a specific) is not a blend here
    _d(6, [], []),                                    # no reading: excluded
]


def model(ds, user_first):
    PRIM = {"Joy", "Trust", "Fear", "Surprise", "Sadness", "Disgust", "Anger", "Anticipation"}
    counts, denom = {}, 0
    for d in ds:
        rep = [w for w in dict.fromkeys(d["emotions_reported"]) if w in PRIM]
        tags = rep if (user_first and rep) else (d["emotions_plutchik"] or d["emotions_reported"])
        seen = [t for t in dict.fromkeys(tags)
                if t in PRIM | {"Love", "Submission", "Awe", "Disapproval", "Remorse", "Contempt", "Aggressiveness", "Optimism"}]
        if not seen:
            continue
        denom += 1
        for t in seen:
            counts[t] = counts.get(t, 0) + 1
    return counts, denom


NAME = {"Joy": "Happy", "Sadness": "Sad", "Anger": "Angry"}


def _landscape(browser, ds):
    ctx, page, st = make(browser, width=390, height=844, dreams=ds)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=patterns]').click()")
    page.wait_for_timeout(900)
    if page.locator("#insights-legend-toggle").count():
        page.click("#insights-legend-toggle")
        page.wait_for_timeout(300)
    txt = page.inner_text(".emotion-legend")
    got = {}
    for m in re.finditer(r"(\w+) — (\d+)/(\d+)", txt):
        got[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    caption = " ".join(page.locator(".emotion-caption").all_inner_texts())
    errs = st["errors"]
    ctx.close()
    return got, caption, errs


def test_after_counts_match_the_documented_rule_and_differ_from_before(browser):
    before, bd = model(DATASET, False)
    after, ad = model(DATASET, True)
    assert before != after                                    # the change is real and visible
    assert after == {"Fear": 2, "Joy": 2, "Sadness": 1, "Disgust": 1} and ad == 5
    got, caption, errs = _landscape(browser, DATASET)
    assert errs == []
    for emo, n in after.items():
        assert got[NAME.get(emo, emo)] == (n, ad), (emo, got)
    assert set(got) == {NAME.get(e, e) for e in after}        # nothing extra (no Awe/Contempt/Anger from the AI for user-read dreams)


def test_blend_names_in_reported_are_never_mapped(browser):
    ds = [_d(1, ["Awe", "Contempt", "Disapproval"], ["Disgust"])]
    got, caption, errs = _landscape(browser, ds)
    assert got == {"Disgust": (1, 1)}


def test_dreams_without_a_selection_are_unchanged(browser):
    ds = [_d(i, [], p) for i, p in enumerate([["Fear"], ["Fear", "Trust"], ["Anger"]], 1)]
    ok = model(ds, True)[0] == model(ds, False)[0]
    assert ok
    got, caption, errs = _landscape(browser, ds)
    assert got["Fear"] == (2, 3) and got["Trust"] == (1, 3) and got["Angry"] == (1, 3)
    assert "you selected" not in caption


def test_caption_states_how_many_dreams_use_the_dreamers_selection(browser):
    got, caption, errs = _landscape(browser, DATASET)
    assert "3 of these 5 dreams use the emotions you selected; the rest use Loominous" in caption
    all_user = [_d(i, ["Fear"], ["Anger"]) for i in range(1, 4)]
    got, caption, errs = _landscape(browser, all_user)
    assert "Based on the emotions you selected." in caption and got == {"Fear": (3, 3)}


def test_stored_records_are_not_mutated(browser):
    import copy
    snap = copy.deepcopy(DATASET)
    _landscape(browser, DATASET)
    assert DATASET == snap
