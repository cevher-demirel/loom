"""Stage 19: the emotion taxonomy must be byte-for-byte the pre-Stage-19 one
(ids, labels, hierarchy, colours, plutchik mapping)."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def test_taxonomy_matches_baseline_snapshot():
    m = re.search(r"STAGE15_TAXONOMY_START \*/\s*var EMOTION_TAXONOMY = (.*?);\s*/\* STAGE15_TAXONOMY_END", HTML, re.S)
    now = json.loads(m.group(1))
    base = json.loads((ROOT / "tests" / "fixtures" / "emotion_taxonomy_baseline.json").read_text())
    assert now == base


def test_by_category_interface_is_gone():
    for dead in ("data-feel-view", "feel-tile", "feel-grid", "data-feel-done", "By Category"):
        assert dead not in HTML, dead


def test_single_selection_store():
    # one authoritative selection structure drives wheel, panel, tray and payload
    assert HTML.count("var feelOrder = []") == 1 and HTML.count("var feelSel = {}") == 1
