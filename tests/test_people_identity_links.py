"""
Stage 8 Phase B.1 Priority 2: persistent, reversible People identity
corrections ("Same person?" / "Keep separate", layered on top of Phase
B's own deterministic resolution in index.html --
personIdentityOverridesByKey / resolvePersonMention /
personIdentitySuggestionsFor).

Same extraction-and-run-under-Node approach as test_people_identity.py
and test_duplicate_suppression.py: the real function source is pulled
verbatim out of index.html, so these tests fail the moment the shipped
behavior changes, not just a Python reimplementation of it. The backend
side of Phase B.1 (the person_identity_links table and the
/people/identity-links endpoints these functions call) is covered
separately in tests/test_database.py and tests/test_main.py.
"""
import json
import subprocess
import shutil
from pathlib import Path

import pytest

INDEX_HTML = Path(__file__).resolve().parent.parent / "index.html"


def _slice(text, start_marker, end_marker, search_from=0):
    start = text.index(start_marker, search_from)
    end = text.index(end_marker, start) + len(end_marker)
    return text[start:end], end


@pytest.fixture(scope="module")
def identity_links_js():
    """Same contiguous extraction window test_people_identity.py uses
    (ELEMENT_CATEGORIES through the end of collectDreamElements) --
    Phase B.1's override layer (personIdentityOverridesByKey,
    resolvePersonMention's override checks, personIdentityTargetLabel,
    personIdentitySuggestionsFor) lives entirely inside that same span,
    right alongside the Phase B code it builds on. loadPersonIdentityLinks/
    savePersonIdentityLink/deletePersonIdentityLink are also captured
    here (they call authedFetch, which doesn't exist in this harness),
    but that's harmless -- these tests never call them, only read/write
    personIdentityOverridesByKey directly, the same way the real UI
    handler does once a save/delete call already resolved."""
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
    assert "personIdentityOverridesByKey" in phase_b_block, "extraction boundary drifted -- update the markers above"
    assert "function personIdentitySuggestionsFor(" in phase_b_block
    assert "function resolvePersonMention(" in phase_b_block

    compute_counts_block, cursor = _slice(
        text, "function computeElementCounts(dreams) {", "\n  }\n", cursor
    )

    # authedFetch is referenced (never called) inside
    # loadPersonIdentityLinks/savePersonIdentityLink/
    # deletePersonIdentityLink -- a plain stub is enough since nothing
    # here invokes those three functions.
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


def _resolve(js_source, dreams, overrides, raw):
    """Sets currentDreams and personIdentityOverridesByKey exactly as
    the real app would after loadPersonIdentityLinks resolves, then
    resolves one raw mention the same way collectDreamElements does."""
    driver = (
        "currentDreams = " + json.dumps(dreams) + ";\n"
        "personIdentityOverridesByKey = " + json.dumps(overrides) + ";\n"
        "const index = getPersonIdentityIndex();\n"
        "console.log(JSON.stringify(resolvePersonMention(" + json.dumps(raw) + ", index)));\n"
    )
    return _run(js_source, driver)


def _element_counts(js_source, dreams, overrides):
    driver = (
        "currentDreams = " + json.dumps(dreams) + ";\n"
        "personIdentityOverridesByKey = " + json.dumps(overrides) + ";\n"
        "const counts = computeElementCounts(currentDreams).filter(e => e.category === 'person');\n"
        "console.log(JSON.stringify(counts));\n"
    )
    return _run(js_source, driver)


def _suggestions(js_source, dreams, role_term):
    driver = (
        "currentDreams = " + json.dumps(dreams) + ";\n"
        "const index = getPersonIdentityIndex();\n"
        "console.log(JSON.stringify(personIdentitySuggestionsFor(" + json.dumps(role_term) + ", index)));\n"
    )
    return _run(js_source, driver)


# ---------------------------------------------------------------------
# 'separate' override: un-merges an automatic single-candidate role
# merge (the "my girlfriend" / Abby case from the Phase B.1 brief).
# ---------------------------------------------------------------------

def test_separate_override_undoes_automatic_role_merge(identity_links_js):
    dreams = [_dream(1, ["girlfriend Abby"]), _dream(2, ["my girlfriend"])]
    # Baseline, no override: "my girlfriend" automatically merges into Abby.
    without = _resolve(identity_links_js, dreams, {}, "my girlfriend")
    assert without["key"] == "abby"
    assert without["ambiguousRole"] is False

    # With an explicit 'separate' correction on the role bucket, "my
    # girlfriend" stays its own identity even though Abby is still the
    # only named girlfriend on record.
    overrides = {"role:girlfriend": {"decision": "separate", "target_key": "", "target_label": ""}}
    with_sep = _resolve(identity_links_js, dreams, overrides, "my girlfriend")
    assert with_sep["key"] == "role:girlfriend"
    assert with_sep["ambiguousRole"] is True

    # A genuine bare "Abby" mention is completely unaffected by that
    # correction -- it's still just Abby.
    abby = _resolve(identity_links_js, dreams, overrides, "Abby")
    assert abby["key"] == "abby"


def test_separate_override_reflected_in_element_counts(identity_links_js):
    dreams = [_dream(1, ["girlfriend Abby"]), _dream(2, ["my girlfriend"]), _dream(3, ["my girlfriend"])]
    overrides = {"role:girlfriend": {"decision": "separate", "target_key": "", "target_label": ""}}
    counts = _element_counts(identity_links_js, dreams, overrides)
    by_key = {c["catKey"]: c for c in counts}
    assert by_key["person:abby"]["count"] == 1
    assert by_key["person:role:girlfriend"]["count"] == 2
    assert by_key["person:role:girlfriend"]["ambiguousRole"] is True


# ---------------------------------------------------------------------
# 'merge' override on a role bucket: confirms an otherwise-ambiguous
# role ("my brother", with two named brothers on record) as a specific
# person.
# ---------------------------------------------------------------------

def test_merge_override_resolves_an_ambiguous_role_bucket(identity_links_js):
    dreams = [_dream(1, ["brother James"]), _dream(2, ["brother Michael"]), _dream(3, ["my brother"])]
    # Baseline: two named brothers on record -> "my brother" stays ambiguous.
    without = _resolve(identity_links_js, dreams, {}, "my brother")
    assert without["key"] == "role:brother"
    assert without["ambiguousRole"] is True

    overrides = {"role:brother": {"decision": "merge", "target_key": "james", "target_label": "James"}}
    confirmed = _resolve(identity_links_js, dreams, overrides, "my brother")
    assert confirmed["key"] == "james"
    assert confirmed["ambiguousRole"] is False
    assert confirmed["label"] == "James"

    # The other named brother is never touched by this correction.
    michael = _resolve(identity_links_js, dreams, overrides, "brother Michael")
    assert michael["key"] == "michael"


def test_merge_override_target_label_is_preferred_over_live_lookup(identity_links_js):
    """target_label is saved at correction time and preferred over
    re-deriving a display label from the current archive, so a
    correction keeps reading sensibly even if its target's own bare
    mention is edited or removed later."""
    dreams = [_dream(1, ["my brother"])]  # "james" never appears as a bare mention in this archive at all
    overrides = {"role:brother": {"decision": "merge", "target_key": "james", "target_label": "James Whitfield"}}
    resolved = _resolve(identity_links_js, dreams, overrides, "my brother")
    assert resolved["key"] == "james"
    assert resolved["label"] == "James Whitfield"


# ---------------------------------------------------------------------
# Reversal: removing the override row (simulated here by simply not
# including it) restores exactly the original deterministic behavior.
# ---------------------------------------------------------------------

def test_reversal_is_simply_the_absence_of_the_override_row(identity_links_js):
    dreams = [_dream(1, ["girlfriend Abby"]), _dream(2, ["my girlfriend"])]
    sep = {"role:girlfriend": {"decision": "separate", "target_key": "", "target_label": ""}}
    assert _resolve(identity_links_js, dreams, sep, "my girlfriend")["key"] == "role:girlfriend"
    # No "undo" primitive beyond removing the row -- passing {} (the
    # shape loadPersonIdentityLinks leaves things in after a delete)
    # reproduces the exact pre-correction automatic behavior.
    assert _resolve(identity_links_js, dreams, {}, "my girlfriend")["key"] == "abby"


# ---------------------------------------------------------------------
# A 'separate' override on a bare name is a no-op -- names were never
# automatically merged with anything, so there's nothing to undo.
# ---------------------------------------------------------------------

def test_separate_override_on_a_bare_name_is_a_noop(identity_links_js):
    dreams = [_dream(1, ["Bob"])]
    overrides = {"bob": {"decision": "separate", "target_key": "", "target_label": ""}}
    resolved = _resolve(identity_links_js, dreams, overrides, "Bob")
    assert resolved["key"] == "bob"
    assert resolved["ambiguousRole"] is False


# ---------------------------------------------------------------------
# A 'merge' override directly on a plain name key -- linking two
# distinct named identities the user has manually confirmed are the
# same real person (e.g. "Bob" and "Robert"), never inferred automatically.
# ---------------------------------------------------------------------

def test_merge_override_links_two_distinct_named_identities(identity_links_js):
    dreams = [_dream(1, ["Bob"]), _dream(2, ["Robert"])]
    without = _resolve(identity_links_js, dreams, {}, "Bob")
    assert without["key"] == "bob"  # never auto-merged -- two different names, no shared evidence

    overrides = {"bob": {"decision": "merge", "target_key": "robert", "target_label": "Robert"}}
    merged = _resolve(identity_links_js, dreams, overrides, "Bob")
    assert merged["key"] == "robert"
    # The target identity itself is untouched.
    robert = _resolve(identity_links_js, dreams, overrides, "Robert")
    assert robert["key"] == "robert"


# ---------------------------------------------------------------------
# personIdentitySuggestionsFor: only ever offers already-named
# candidates for that exact role, excluding whichever one the automatic
# rule would already resolve to -- never a fuzzy/invented match.
# ---------------------------------------------------------------------

def test_suggestions_lists_named_candidates_for_an_ambiguous_role(identity_links_js):
    dreams = [_dream(1, ["brother James"]), _dream(2, ["brother Michael"]), _dream(3, ["my brother"])]
    suggestions = _suggestions(identity_links_js, dreams, "brother")
    keys = sorted(s["key"] for s in suggestions)
    assert keys == ["james", "michael"]


def test_suggestions_empty_for_a_role_with_no_named_candidates(identity_links_js):
    dreams = [_dream(1, ["my brother"])]  # no name ever given for "brother"
    suggestions = _suggestions(identity_links_js, dreams, "brother")
    assert suggestions == []


def test_suggestions_exclude_the_already_automatic_candidate(identity_links_js):
    dreams = [_dream(1, ["girlfriend Abby"]), _dream(2, ["my girlfriend"])]
    # Only one named candidate -> it's already the automatic resolution,
    # so there's nothing left to "suggest confirming."
    suggestions = _suggestions(identity_links_js, dreams, "girlfriend")
    assert suggestions == []


# ---------------------------------------------------------------------
# Malformed/missing data doesn't crash resolution, override or no.
# ---------------------------------------------------------------------

def test_overrides_do_not_crash_on_malformed_people_data(identity_links_js):
    dreams = [
        {"id": 1, "timestamp": "2024-01-01", "people": [None, "", "   ", "Abby"],
         "symbols": [], "emotions": [], "settings": [], "themes": [], "symbol_icons": {}},
        {"id": 2, "timestamp": "2024-01-02", "symbols": [], "emotions": [], "settings": [], "themes": [], "symbol_icons": {}},
    ]
    overrides = {"role:girlfriend": {"decision": "separate", "target_key": "", "target_label": ""}}
    counts = _element_counts(identity_links_js, dreams, overrides)
    assert any(c["catKey"] == "person:abby" for c in counts)
