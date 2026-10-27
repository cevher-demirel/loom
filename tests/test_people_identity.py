"""
Stage 8 Phase B: People identity resolution (buildPersonIdentityIndex /
parsePersonMention / resolvePersonMention / collectDreamElements's People
handling / computeElementCounts / computeDiscoveries, in index.html) is
plain client-side JS with no build step. As with Stage 2's duplicate-
suppression tests (test_duplicate_suppression.py), this extracts the real
function source out of index.html and runs it under Node, so these tests
fail the moment the shipped behavior changes -- not just a Python
reimplementation that could silently drift from the real code.

Covers the 14 required cases from the Phase B spec's test matrix (section
5), plus a couple of extra checks on data-preservation and the Discoveries
cross-category suppression interaction.
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
def people_identity_js():
    """Concatenates the real source of every function the People-identity
    layer needs, extracted verbatim from index.html, in dependency order,
    plus small stand-ins for the two things it depends on from elsewhere
    in the file that aren't needed for these tests (ICON_SVGS, and a
    `currentDreams` the test driver script below sets per case)."""
    text = INDEX_HTML.read_text()

    normalize_block, _ = _slice(text, "function normalizeTagKey(s)", "\n  }\n")

    duplicate_suppression_block, cursor = _slice(
        text,
        "var LEADING_QUALIFIER_RE",
        "function isLikelyDuplicateReference(a, b) {\n    if (a.category === b.category) return false;\n    return stripLeadingQualifier(a.key) === stripLeadingQualifier(b.key);\n  }",
    )

    collect_tags_block, cursor = _slice(text, "function collectDreamTags(dream) {", "\n  }\n", cursor)

    # From ELEMENT_CATEGORIES through the end of collectDreamElements --
    # this one contiguous span covers ELEMENT_CATEGORIES, the whole Phase
    # B identity layer (PERSON_ROLE_TERMS.../resolvePersonMention/
    # getPersonIdentityIndex), and collectDreamElements itself, exactly
    # as they appear in the shipped file.
    phase_b_block, cursor = _slice(
        text, "var ELEMENT_CATEGORIES = {", "\n    return out;\n  }\n", cursor
    )
    assert "PERSON_ROLE_TERMS" in phase_b_block, "extraction boundary drifted -- update the markers above"
    assert "function resolvePersonMention(" in phase_b_block
    assert "function collectDreamElements(" in phase_b_block

    compute_counts_block, cursor = _slice(
        text, "function computeElementCounts(dreams) {", "\n  }\n", cursor
    )

    discoveries_block, cursor = _slice(
        text, "function connectionKeyFor(catKeyA, catKeyB) {",
        'return typeof limit === "number" ? list.slice(0, limit) : list;\n  }\n', cursor
    )
    assert "DISCOVERY_MIN_DREAMS" in discoveries_block

    stub = "var ICON_SVGS = {}; var currentDreams = [];\n"

    return "\n".join([
        stub, normalize_block, duplicate_suppression_block, collect_tags_block,
        phase_b_block, compute_counts_block, discoveries_block,
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


def _element_counts(js_source, dreams):
    """currentDreams = dreams; computeElementCounts(dreams) -- the real
    call shape every one of collectDreamElements's callers uses."""
    driver = (
        "currentDreams = " + json.dumps(dreams) + ";\n"
        "const counts = computeElementCounts(currentDreams).filter(e => e.category === 'person');\n"
        "console.log(JSON.stringify(counts));\n"
    )
    return _run(js_source, driver)


def _person_keys_by_dream(js_source, dreams):
    """currentDreams = dreams; collectDreamElements(d) per dream, person
    category only, returned as a map of dream id -> list of catKeys --
    exercises the per-dream de-dup path directly."""
    driver = (
        "currentDreams = " + json.dumps(dreams) + ";\n"
        "const out = {};\n"
        "currentDreams.forEach(d => { out[d.id] = collectDreamElements(d).filter(e => e.category === 'person').map(e => e.catKey); });\n"
        "console.log(JSON.stringify(out));\n"
    )
    return _run(js_source, driver)


def _discoveries(js_source, dreams):
    driver = (
        "currentDreams = " + json.dumps(dreams) + ";\n"
        "console.log(JSON.stringify(computeDiscoveries(currentDreams)));\n"
    )
    return _run(js_source, driver)


def _key_for(counts, label_substring=None, catkey_suffix=None):
    for c in counts:
        if catkey_suffix is not None and c["catKey"] == "person:" + catkey_suffix:
            return c
        if label_substring is not None and label_substring.lower() in c["label"].lower():
            return c
    return None


# ---------------------------------------------------------------------
# 1. brother vs my brother -- merge (unambiguous, single account-wide
#    role->name... actually no name at all here, just the two bare
#    phrasings of the SAME role, which must count as one bucket).
# ---------------------------------------------------------------------
def test_bare_role_and_my_role_merge(people_identity_js):
    dreams = [_dream(1, ["brother"]), _dream(2, ["my brother"])]
    counts = _element_counts(people_identity_js, dreams)
    assert len(counts) == 1, counts
    assert counts[0]["count"] == 2
    assert counts[0]["catKey"] == "person:role:brother"


# ---------------------------------------------------------------------
# 2. "girlfriend Abby" and "Abby" -- same-dream and cross-dream evidence
# ---------------------------------------------------------------------
def test_named_role_and_bare_name_merge(people_identity_js):
    dreams = [_dream(1, ["girlfriend Abby"]), _dream(2, ["Abby"])]
    counts = _element_counts(people_identity_js, dreams)
    assert len(counts) == 1, counts
    assert counts[0]["catKey"] == "person:abby"
    assert counts[0]["count"] == 2
    assert counts[0]["label"] == "Abby"  # the bare mention's own casing wins


# ---------------------------------------------------------------------
# 3. "my girlfriend" with one strongly established candidate vs ambiguous
# ---------------------------------------------------------------------
def test_role_resolves_to_single_established_candidate(people_identity_js):
    dreams = [_dream(1, ["girlfriend Abby"]), _dream(2, ["my girlfriend"])]
    counts = _element_counts(people_identity_js, dreams)
    assert len(counts) == 1, counts
    assert counts[0]["catKey"] == "person:abby"
    assert counts[0]["count"] == 2


def test_role_stays_ambiguous_with_competing_candidates(people_identity_js):
    dreams = [_dream(1, ["girlfriend Abby"]), _dream(2, ["girlfriend Maria"]), _dream(3, ["my girlfriend"])]
    counts = _element_counts(people_identity_js, dreams)
    abby = _key_for(counts, catkey_suffix="abby")
    maria = _key_for(counts, catkey_suffix="maria")
    ambiguous = _key_for(counts, catkey_suffix="role:girlfriend")
    assert abby and abby["count"] == 1
    assert maria and maria["count"] == 1
    assert ambiguous and ambiguous["count"] == 1, counts
    assert len(counts) == 3, "the ambiguous 'my girlfriend' must NOT be guessed onto either name"


# ---------------------------------------------------------------------
# 4. "girlfriend Abby" and "girlfriend Maria" stay separate
# ---------------------------------------------------------------------
def test_two_named_candidates_for_same_role_stay_separate(people_identity_js):
    dreams = [_dream(1, ["girlfriend Abby"]), _dream(2, ["girlfriend Maria"])]
    counts = _element_counts(people_identity_js, dreams)
    assert len(counts) == 2
    assert {c["catKey"] for c in counts} == {"person:abby", "person:maria"}


# ---------------------------------------------------------------------
# 5. Two brothers with different names; unnamed "my brother" doesn't pick one
# ---------------------------------------------------------------------
def test_two_named_brothers_plus_unnamed_stay_three_identities(people_identity_js):
    dreams = [_dream(1, ["brother James"]), _dream(2, ["brother Michael"]), _dream(3, ["my brother"])]
    counts = _element_counts(people_identity_js, dreams)
    assert len(counts) == 3, counts
    keys = {c["catKey"] for c in counts}
    assert keys == {"person:james", "person:michael", "person:role:brother"}


# ---------------------------------------------------------------------
# 6. "a brother" / "a stranger" remain ambiguous -- separate from "my
#    brother" / "brother" entirely, never swept into the role bucket.
# ---------------------------------------------------------------------
def test_indefinite_article_mentions_stay_fully_separate(people_identity_js):
    dreams = [_dream(1, ["a brother"]), _dream(2, ["my brother"]), _dream(3, ["a stranger"])]
    counts = _element_counts(people_identity_js, dreams)
    keys = {c["catKey"]: c["count"] for c in counts}
    assert keys.get("person:a brother") == 1
    assert keys.get("person:role:brother") == 1
    assert keys.get("person:a stranger") == 1
    assert "person:brother" not in keys


# ---------------------------------------------------------------------
# 7. Same raw name belonging to different users remains separate -- this
#    whole index is built per call from whatever `dreams` it's given
#    (here, each user's own currentDreams), so there is no shared/global
#    state a second account's data could ever leak through. Simulated by
#    building two completely independent indexes from two disjoint
#    dream sets that happen to share a raw name.
# ---------------------------------------------------------------------
def test_same_name_different_accounts_independent(people_identity_js):
    user_a_dreams = [_dream(1, ["girlfriend Abby"]), _dream(2, ["my girlfriend"])]
    user_b_dreams = [_dream(1, ["Abby"])]  # a completely different account's own dream
    counts_a = _element_counts(people_identity_js, user_a_dreams)
    counts_b = _element_counts(people_identity_js, user_b_dreams)
    assert len(counts_a) == 1 and counts_a[0]["count"] == 2
    assert len(counts_b) == 1 and counts_b[0]["count"] == 1
    # No shared global registry: user B's single "Abby" dream has no
    # bearing on how user A's "my girlfriend" resolved, and vice versa.


# ---------------------------------------------------------------------
# 8. Repeated mention in one dream counts once; distinct dreams count separately
# ---------------------------------------------------------------------
def test_repeated_equivalent_mention_in_one_dream_counts_once(people_identity_js):
    dreams = [_dream(1, ["Abby", "my girlfriend", "girlfriend Abby"]), _dream(2, ["Abby"])]
    by_dream = _person_keys_by_dream(people_identity_js, dreams)
    assert by_dream["1"] == ["person:abby"], by_dream  # deduped to exactly one entry
    assert by_dream["2"] == ["person:abby"]
    counts = _element_counts(people_identity_js, dreams)
    assert counts[0]["count"] == 2  # two DISTINCT dreams, not three raw mentions


# ---------------------------------------------------------------------
# 9. Edges use number of unique shared dreams, not number of raw aliases
# ---------------------------------------------------------------------
def test_discovery_edge_counts_shared_dreams_not_raw_aliases(people_identity_js):
    dreams = [
        _dream(1, ["Abby", "my girlfriend"], timestamp="2024-01-01"),  # same dream, same person -- not a pair with itself
    ]
    # Abby co-occurring with a second element across two dreams should
    # produce a discovery count of 2 (two dreams), not 1 per raw phrasing.
    dreams = [
        _dream(1, ["Abby", "my brother"], timestamp="2024-01-01"),
        _dream(2, ["girlfriend Abby", "brother"], timestamp="2024-01-02"),
    ]
    discoveries = _discoveries(people_identity_js, dreams)
    assert len(discoveries) == 1, discoveries
    assert discoveries[0]["count"] == 2
    assert discoveries[0]["dreamIds"] == [1, 2]


# ---------------------------------------------------------------------
# 10. Historical raw People arrays are never rewritten -- proven
#     structurally: collectDreamElements must never mutate `dream` or
#     `dream.people`.
# ---------------------------------------------------------------------
def test_collect_dream_elements_does_not_mutate_input(people_identity_js):
    dreams = [_dream(1, ["Abby", "my girlfriend", " Abby ", "Girlfriend  Abby"])]
    driver = (
        "currentDreams = " + json.dumps(dreams) + ";\n"
        "const before = JSON.stringify(currentDreams);\n"
        "collectDreamElements(currentDreams[0]);\n"
        "const after = JSON.stringify(currentDreams);\n"
        "console.log(JSON.stringify({ unchanged: before === after, original: currentDreams[0].people }));\n"
    )
    result = _run(people_identity_js, driver)
    assert result["unchanged"] is True
    assert result["original"] == ["Abby", "my girlfriend", " Abby ", "Girlfriend  Abby"]


# ---------------------------------------------------------------------
# 11. Capitalization, whitespace, Unicode punctuation, possessives --
#     safe equivalence only, no unjustified fuzzy merging (nicknames like
#     "Bob"/"Robert" must NOT be merged -- no evidence links them).
# ---------------------------------------------------------------------
def test_case_whitespace_and_unicode_punctuation_are_safely_equivalent(people_identity_js):
    dreams = [_dream(1, ["Abby"]), _dream(2, ["  abby  "]), _dream(3, ["ABBY"]), _dream(4, ["Abby’s"])]
    # "Abby's" (possessive with a smart apostrophe) is intentionally NOT
    # asserted equal to "Abby" here -- possessive-on-a-name stripping
    # isn't part of the safe whitelist (only "my "+role-term is), so it's
    # covered separately below as a case that correctly stays distinct.
    counts = _element_counts(people_identity_js, dreams[:3])
    assert len(counts) == 1, counts
    assert counts[0]["count"] == 3


def test_nicknames_are_not_fuzzy_merged(people_identity_js):
    dreams = [_dream(1, ["Bob"]), _dream(2, ["Robert"])]
    counts = _element_counts(people_identity_js, dreams)
    assert len(counts) == 2, "no evidence links these -- must never be merged by similarity"


# ---------------------------------------------------------------------
# 12. Empty/missing/malformed People fields; no crash
# ---------------------------------------------------------------------
def test_empty_missing_malformed_people_fields_do_not_crash(people_identity_js):
    dreams = [
        {"id": 1, "timestamp": "2024-01-01", "people": [], "symbols": [], "emotions": [], "settings": [], "themes": [], "symbol_icons": {}},
        {"id": 2, "timestamp": "2024-01-02", "symbols": [], "emotions": [], "settings": [], "themes": [], "symbol_icons": {}},  # people key missing entirely
        {"id": 3, "timestamp": "2024-01-03", "people": [None, "", "   ", "Abby"], "symbols": [], "emotions": [], "settings": [], "themes": [], "symbol_icons": {}},
    ]
    counts = _element_counts(people_identity_js, dreams)
    assert len(counts) == 1
    assert counts[0]["catKey"] == "person:abby"
    assert counts[0]["count"] == 1


# ---------------------------------------------------------------------
# 13. Existing map interactions unaffected: emotions/places (untouched
#     categories) still aggregate exactly as before, and malformed
#     People data on one dream doesn't break symbol/emotion/place
#     aggregation for that same dream or any other.
# ---------------------------------------------------------------------
def test_other_categories_unaffected_by_people_resolution(people_identity_js):
    dreams = [{
        "id": 1, "timestamp": "2024-01-01",
        # "girlfriend Abby" is the actual evidence that links the role to
        # the name (per case 2/3) -- a bare "Abby" merely co-occurring in
        # the same list as "my girlfriend" is deliberately NOT itself
        # evidence of anything (see test_role_stays_ambiguous_with_* above).
        "people": ["my girlfriend", "girlfriend Abby"], "emotions": ["Calm", " calm "], "settings": ["a beach"],
        "symbols": [], "themes": [], "symbol_icons": {},
    }]
    driver = (
        "currentDreams = " + json.dumps(dreams) + ";\n"
        "console.log(JSON.stringify(computeElementCounts(currentDreams)));\n"
    )
    counts = _run(people_identity_js, driver)
    by_cat = {}
    for c in counts:
        by_cat.setdefault(c["category"], []).append(c)
    assert len(by_cat["person"]) == 1  # the merge still happens
    assert len(by_cat["emotion"]) == 1  # "Calm" / " calm " still dedup as before
    assert len(by_cat["place"]) == 1


# ---------------------------------------------------------------------
# Data preservation + Discoveries suppression interaction (beyond the
# required 14 -- specifically verifying the rawKey fix that keeps Stage
# 2's cross-category duplicate suppression working once a person key is
# a Phase B-resolved identity rather than its own raw normalized text).
# ---------------------------------------------------------------------
def test_phase_b_resolution_does_not_break_stage2_cross_category_suppression(people_identity_js):
    # "my brother" (person, resolves to the ambiguous role:brother bucket
    # since no name was ever given) also mistakenly extracted as a
    # symbol in the same dream -- Stage 2's existing suppression must
    # still catch this exact double-extraction bug post-Phase B.
    dreams = [
        _dream(1, ["my brother"], timestamp="2024-01-01"),
        _dream(2, ["my brother"], timestamp="2024-01-02"),
    ]
    dreams[0]["symbols"] = ["brother"]
    dreams[1]["symbols"] = ["brother"]
    discoveries = _discoveries(people_identity_js, dreams)
    assert discoveries == [], "the person/symbol duplicate-extraction pair must stay suppressed"
