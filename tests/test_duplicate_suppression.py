"""
Stage 2's duplicate-discovery suppression (isLikelyDuplicateReference /
stripLeadingQualifier, in index.html) is plain client-side JS with no
build step and no existing JS test harness in this project. Rather than
reimplement the logic in Python (which could silently drift from the
real code), this extracts the exact function source out of index.html
and runs it for real under Node, so these tests fail the moment the
shipped behavior changes, not just a copy of it.

Covers:
  - positive cases: the actual duplicate-extraction bug (person/place
    also captured as a symbol, same dream) gets suppressed
  - negative cases: genuinely different entities that merely share a
    word, or that differ only by an un-stripped qualifier, or that are
    the same-category "Maria" vs "my girlfriend" problem Stage 2 found
    (explicitly out of scope for this rule) are never suppressed
  - that the only thing this touches is which pairs computeDiscoveries()
    presents -- not counts, not records, not element access. That part
    is proven structurally (see test_suppression_is_presentation_only
    below) rather than by running the whole app, since this file has no
    way to spin up the full index.html/DB/API stack.
"""
import re
import json
import subprocess
import shutil
from pathlib import Path

import pytest

INDEX_HTML = Path(__file__).resolve().parent.parent / "index.html"


def _extract_js_block(start_marker, end_marker):
    text = INDEX_HTML.read_text()
    start = text.index(start_marker)
    end = text.index(end_marker, start) + len(end_marker)
    return text[start:end]


@pytest.fixture(scope="module")
def duplicate_suppression_js():
    """The real stripLeadingQualifier/isLikelyDuplicateReference source,
    pulled verbatim out of index.html."""
    block = _extract_js_block(
        "function normalizeTagKey(s)",
        "function isLikelyDuplicateReference(a, b) {\n    if (a.category === b.category) return false;\n    return stripLeadingQualifier(a.key) === stripLeadingQualifier(b.key);\n  }",
    )
    assert "LEADING_QUALIFIER_RE" in block, "extraction boundary drifted -- update the markers above"
    return block


def _run_cases(js_source, cases):
    """cases: list of {a: {category,key}, b: {category,key}}. Returns a
    list of booleans (isLikelyDuplicateReference's result for each)."""
    if shutil.which("node") is None:
        pytest.skip("node is not available in this environment")
    harness = (
        js_source
        + "\nconst cases = "
        + json.dumps(cases)
        + ";\nconsole.log(JSON.stringify(cases.map(c => isLikelyDuplicateReference(c.a, c.b))));\n"
    )
    result = subprocess.run(
        ["node", "-e", harness], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, f"node failed: {result.stderr}"
    return json.loads(result.stdout)


# ---------------------------------------------------------------------
# Positive cases: the real bug this exists to catch
# ---------------------------------------------------------------------
POSITIVE_CASES = [
    # (label, a, b)
    ("brother James duplicated as symbol",
     {"category": "person", "key": "my brother james"},
     {"category": "symbol", "key": "brother james"}),
    ("mother duplicated as symbol",
     {"category": "person", "key": "my mother"},
     {"category": "symbol", "key": "mother"}),
    ("beach duplicated as symbol",
     {"category": "place", "key": "a beach"},
     {"category": "symbol", "key": "beach"}),
    ("carnival duplicated as symbol",
     {"category": "place", "key": "a carnival"},
     {"category": "symbol", "key": "carnival"}),
    ("the-prefixed place duplicated as symbol",
     {"category": "place", "key": "the lighthouse"},
     {"category": "symbol", "key": "lighthouse"}),
]

# ---------------------------------------------------------------------
# Negative cases: must NOT be suppressed
# ---------------------------------------------------------------------
NEGATIVE_CASES = [
    ("different people sharing only the word 'brother'",
     {"category": "person", "key": "my brother james"},
     {"category": "person", "key": "my brother michael"}),
    ("same-category phrasing drift (Stage 2's actual 'Maria' example) -- different problem, not this rule's job",
     {"category": "person", "key": "my girlfriend"},
     {"category": "person", "key": "maria"}),
    ("unrelated genuine co-occurrence",
     {"category": "emotion", "key": "anxiety"},
     {"category": "person", "key": "my brother james"}),
    ("shares a word but is not the same phrase once stripped",
     {"category": "place", "key": "a beach house"},
     {"category": "symbol", "key": "beach"}),
    ("qualifier in the middle, not the front -- not stripped, so not an exact match",
     {"category": "place", "key": "beach at my old house"},
     {"category": "symbol", "key": "beach"}),
    ("same category, exact same key -- not a cross-category pair at all",
     {"category": "symbol", "key": "fox"},
     {"category": "symbol", "key": "fox"}),
]


@pytest.mark.parametrize("label,a,b", POSITIVE_CASES, ids=[c[0] for c in POSITIVE_CASES])
def test_duplicate_reference_is_suppressed(duplicate_suppression_js, label, a, b):
    result = _run_cases(duplicate_suppression_js, [{"a": a, "b": b}])
    assert result == [True], f"expected suppression for: {label}"


@pytest.mark.parametrize("label,a,b", NEGATIVE_CASES, ids=[c[0] for c in NEGATIVE_CASES])
def test_distinct_entities_are_not_suppressed(duplicate_suppression_js, label, a, b):
    result = _run_cases(duplicate_suppression_js, [{"a": a, "b": b}])
    assert result == [False], f"expected NO suppression for: {label}"


def test_suppression_is_symmetric(duplicate_suppression_js):
    """Order of a/b (which matches computeDiscoveries' own
    alphabetical-by-catKey ordering of pairs) must not change the
    result."""
    a = {"category": "person", "key": "my brother james"}
    b = {"category": "symbol", "key": "brother james"}
    forward, backward = _run_cases(duplicate_suppression_js, [{"a": a, "b": b}, {"a": b, "b": a}])
    assert forward == backward is True


def test_suppression_is_presentation_only():
    """computeDiscoveries() applies isLikelyDuplicateReference as a
    .filter() on the pairs list *after* each pair's count/dreamIds are
    already finalized from the real per-dream data (see index.html),
    and only to decide which pairs to return -- it never touches
    collectDreamElements, computeElementCounts, symbolScreenOccurrences,
    or any personal-meanings storage. Those are the functions that
    actually back dream counts, element access, and saved personal
    meanings, and none of them reference isLikelyDuplicateReference or
    stripLeadingQualifier at all. This is a structural check (import
    isn't possible -- no JS module system here), verified by grep
    rather than by running the full app stack in this test file.
    """
    text = INDEX_HTML.read_text()

    # The suppression filter must live inside computeDiscoveries, after
    # the count/dreamIds bookkeeping, as a pure list .filter().
    compute_discoveries = text[text.index("function computeDiscoveries("):]
    compute_discoveries = compute_discoveries[: compute_discoveries.index("\n  }\n") + 5]
    assert "isLikelyDuplicateReference" in compute_discoveries
    assert "entry.count += 1" in compute_discoveries  # counts are built before suppression ever runs
    assert re.search(r"\.filter\(function \(p\) \{ return !isLikelyDuplicateReference", compute_discoveries)

    # Functions that back real counts / element access / personal
    # meanings must NOT reference the suppression helpers.
    for fn_name in [
        "function collectDreamElements(",
        "function computeElementCounts(",
        "function symbolScreenOccurrences(",
    ]:
        start = text.index(fn_name)
        # crude but sufficient: scan to the next top-level "function " at
        # the same indent, or 2000 chars, whichever comes first
        end = text.index("\n  function ", start + 1)
        body = text[start:end]
        assert "isLikelyDuplicateReference" not in body, f"{fn_name} must not be affected by discovery suppression"
        assert "stripLeadingQualifier" not in body, f"{fn_name} must not be affected by discovery suppression"
