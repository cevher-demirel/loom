"""Stage 15: the emotion taxonomy embedded in index.html is complete and
well-formed, and the protected interpretation files were not touched."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
PLUTCHIK = {"joy", "trust", "fear", "surprise", "sadness", "disgust", "anger", "anticipation"}


def _taxonomy():
    m = re.search(r"STAGE15_TAXONOMY_START \*/\s*var EMOTION_TAXONOMY = (.*?);\s*/\* STAGE15_TAXONOMY_END", HTML, re.S)
    assert m, "taxonomy block missing"
    return json.loads(m.group(1))


def test_eight_families_with_plutchik_mapping():
    t = _taxonomy()
    assert len(t) == 8
    assert {f["plutchik"] for f in t} == PLUTCHIK


def test_three_levels_and_unique_ids():
    t = _taxonomy()
    ids = []
    for f in t:
        assert f["children"], f["id"]
        ids.append(f["id"])
        for mid in f["children"]:
            assert mid["children"], mid["id"]
            ids.append(mid["id"])
            for leaf in mid["children"]:
                assert leaf["id"].startswith(mid["id"] + ".")
                ids.append(leaf["id"])
    assert len(ids) == len(set(ids))
    assert sum(len(f["children"]) for f in t) == 40
    assert len(ids) == 8 + 40 + 80


def test_known_paths_from_reference():
    t = {f["id"]: f for f in _taxonomy()}
    fear = {m["label"]: [l["label"] for l in m["children"]] for m in t["fear"]["children"]}
    assert fear["Worried"] == ["Edgy", "Distressed"]
    trust = {m["label"]: [l["label"] for l in m["children"]] for m in t["trust"]["children"]}
    assert trust["Hopeful"] == ["Longing", "Expectant"]


def test_interpretation_engine_unchanged_vs_main():
    import subprocess
    out = subprocess.run(["git", "diff", "--stat", "origin/main", "--", "engine.py", "main.py", "database.py", "vectorstore.py"],
                         cwd=ROOT, capture_output=True, text=True)
    assert out.stdout.strip() == "", out.stdout
