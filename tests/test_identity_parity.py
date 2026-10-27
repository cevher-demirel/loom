"""
tests/test_identity_parity.py -- Stage 8 Phase B.2 Priority 2.

identity.py is a deliberately independent re-derivation of People
identity equivalence (see its own module docstring for why: main.py
can no longer trust a caller-supplied `aliases` list, so it must
recompute equivalence itself from this account's own dreams and saved
corrections, server-side). Being a second implementation of the same
rules as index.html's resolvePersonMention, it carries a real risk of
silently drifting from the client's actual behavior over time.

This file is the drift guard identity.py's docstring promises: for a
shared table of fixtures (dreams + saved identity_links + a raw
mention), it runs the REAL JS source -- extracted verbatim out of
index.html and executed under Node, the same approach
test_people_identity_links.py already uses -- and asserts it resolves
each mention to the exact same identity key identity.resolve_person_key
computes in Python. If a future change to either side's rules isn't
mirrored in the other, one of these fixtures fails.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import identity

INDEX_HTML = Path(__file__).resolve().parent.parent / "index.html"


def _slice(text, start_marker, end_marker, search_from=0):
    start = text.index(start_marker, search_from)
    end = text.index(end_marker, start) + len(end_marker)
    return text[start:end], end


@pytest.fixture(scope="module")
def identity_js():
    """Same contiguous extraction window test_people_identity_links.py
    uses: normalizeTagKey through computeElementCounts covers
    PERSON_ROLE_TERMS, parsePersonMention, buildPersonIdentityIndex and
    resolvePersonMention in one span."""
    text = INDEX_HTML.read_text()

    normalize_block, _ = _slice(text, "function normalizeTagKey(s)", "\n  }\n")

    duplicate_suppression_block, cursor = _slice(
        text,
        "var LEADING_QUALIFIER_RE",
        "function isLikelyDuplicateReference(a, b) {\n    if (a.category === b.category) return false;\n    return stripLeadingQualifier(a.key) === stripLeadingQualifier(b.key);\n  }",
    )

    collect_tags_block, cursor = _slice(text, "function collectDreamTags(dream) {", "\n  }\n", cursor)

    phase_b_block, cursor = _slice(
        text, "var ELEMENT_CATEGORIES = {", "\n    return out;\n  }\n", cursor
    )
    assert "function resolvePersonMention(" in phase_b_block, "extraction boundary drifted -- update the markers above"

    compute_counts_block, cursor = _slice(
        text, "function computeElementCounts(dreams) {", "\n  }\n", cursor
    )

    stub = "var ICON_SVGS = {}; var currentDreams = []; function authedFetch() { throw new Error('not used in this test'); }\n"

    return "\n".join([
        stub, normalize_block, duplicate_suppression_block, collect_tags_block,
        phase_b_block, compute_counts_block,
    ])


def _run(js_source, driver_js):
    if shutil.which("node") is None:
        pytest.skip("node is not available in this environment")
    harness = js_source + "\n" + driver_js
    result = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, f"node failed:\n{result.stderr}\n--- harness ---\n{harness}"
    return json.loads(result.stdout)


def _dream(id, people, timestamp="2024-01-01"):
    return {
        "id": id, "timestamp": timestamp, "people": people,
        "symbols": [], "emotions": [], "settings": [], "themes": [], "symbol_icons": {},
    }


def _js_resolve(js_source, dreams, overrides, raw):
    driver = (
        "currentDreams = " + json.dumps(dreams) + ";\n"
        "personIdentityOverridesByKey = " + json.dumps(overrides) + ";\n"
        "const index = getPersonIdentityIndex();\n"
        "console.log(JSON.stringify(resolvePersonMention(" + json.dumps(raw) + ", index)));\n"
    )
    return _run(js_source, driver)


def _py_resolve(dreams, links, raw):
    """links here uses the same on-the-wire shape as overrides above
    ({subject_key: {decision, target_key, target_label}}) -- converted
    to the list-of-rows shape database.list_person_identity_links
    returns and identity.py actually consumes."""
    rows = [dict(row, subject_key=key) for key, row in links.items()]
    role_resolution = identity.build_role_resolution(d.get("people") for d in dreams)
    overrides = {row["subject_key"]: row for row in rows if row.get("subject_key")}
    return identity.resolve_person_key(raw, role_resolution, overrides)


# A single shared fixture table: (label, dreams, overrides, raw mention).
# Every case here must produce the SAME resolved key on both sides.
PARITY_CASES = [
    (
        "single named candidate auto-merges a bare role",
        [_dream(1, ["girlfriend Abby"]), _dream(2, ["my girlfriend"])],
        {},
        "my girlfriend",
    ),
    (
        "two named candidates leave the role ambiguous",
        [_dream(1, ["brother James"]), _dream(2, ["brother Michael"]), _dream(3, ["my brother"])],
        {},
        "my brother",
    ),
    (
        "no named candidate at all leaves the role as itself",
        [_dream(1, ["my brother"])],
        {},
        "my brother",
    ),
    (
        "a named-role mention resolves to the plain name",
        [_dream(1, ["girlfriend Abby"])],
        {},
        "girlfriend Abby",
    ),
    (
        "a plain name mention is used verbatim",
        [_dream(1, ["Abby"])],
        {},
        "Abby",
    ),
    (
        "an indefinite-article mention never enters role resolution",
        [_dream(1, ["a stranger"])],
        {},
        "a stranger",
    ),
    (
        "an explicit 'separate' correction overrides an automatic single-candidate merge",
        [_dream(1, ["girlfriend Abby"]), _dream(2, ["my girlfriend"])],
        {"role:girlfriend": {"decision": "separate", "target_key": "", "target_label": ""}},
        "my girlfriend",
    ),
    (
        "an explicit 'merge' correction resolves an otherwise-ambiguous role",
        [_dream(1, ["brother James"]), _dream(2, ["brother Michael"]), _dream(3, ["my brother"])],
        {"role:brother": {"decision": "merge", "target_key": "james", "target_label": "James"}},
        "my brother",
    ),
    (
        "a 'merge' correction on a role bucket never touches the OTHER named candidate",
        [_dream(1, ["brother James"]), _dream(2, ["brother Michael"]), _dream(3, ["my brother"])],
        {"role:brother": {"decision": "merge", "target_key": "james", "target_label": "James"}},
        "brother Michael",
    ),
    (
        "a 'merge' correction keyed on a plain name also applies",
        [_dream(1, ["Bob"]), _dream(2, ["Bobby"])],
        {"bobby": {"decision": "merge", "target_key": "bob", "target_label": "Bob"}},
        "Bobby",
    ),
    (
        "a 'separate' correction on a plain name is a no-op (nothing automatic to undo)",
        [_dream(1, ["Abby"])],
        {"abby": {"decision": "separate", "target_key": "", "target_label": ""}},
        "Abby",
    ),
]


@pytest.mark.parametrize("label,dreams,overrides,raw", PARITY_CASES, ids=[c[0] for c in PARITY_CASES])
def test_python_and_js_resolve_the_same_identity_key(identity_js, label, dreams, overrides, raw):
    js_result = _js_resolve(identity_js, dreams, overrides, raw)
    py_key = _py_resolve(dreams, overrides, raw)
    assert py_key == js_result["key"], (
        f"{label}: JS resolved {raw!r} to {js_result['key']!r} but Python resolved it to {py_key!r}"
    )
