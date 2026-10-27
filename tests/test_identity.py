"""
tests/test_identity.py -- unit tests for identity.py, the server-side
People identity-equivalence validator added in Stage 8 Phase B.2
Priority 2 (see identity.py's own module docstring for the full
contract and why it exists: /symbols/insight and /symbols/chat used to
trust a caller-supplied `aliases` list outright).

Covers the adversarial cases the brief calls out by name: unrelated
aliases, two named brothers sharing a role, an ambiguous bare role with
no named candidate, an explicit forced-separation correction, a stale
alias that would have been valid before a correction but no longer is,
and that nothing here ever reaches outside the one user's own data it's
given (the HTTP-level cross-account check lives in test_main.py, since
true account scoping happens at the database.get_all_dreams(user_id)
call site, not inside this module).
"""
import identity


def _dream(people):
    return {"people": people}


# ---------------------------------------------------------------------
# parse_person_mention / normalize_tag_key -- the building blocks
# ---------------------------------------------------------------------

def test_parse_person_mention_bare_role():
    assert identity.parse_person_mention("brother") == {"kind": "role", "role_term": "brother"}
    assert identity.parse_person_mention("My Brother") == {"kind": "role", "role_term": "brother"}


def test_parse_person_mention_named_role():
    m = identity.parse_person_mention("girlfriend Abby")
    assert m == {"kind": "named-role", "role_term": "girlfriend", "name": "abby"}


def test_parse_person_mention_plain_name():
    assert identity.parse_person_mention("Abby") == {"kind": "name", "name": "abby"}
    assert identity.parse_person_mention("a stranger") == {"kind": "name", "name": "a stranger"}


def test_normalize_tag_key_handles_unicode_punctuation_and_case():
    assert identity.normalize_tag_key("Abby’s") == "abby's"
    assert identity.normalize_tag_key("  Girlfriend   Abby  ") == "girlfriend abby"


# ---------------------------------------------------------------------
# build_role_resolution -- the deterministic single-candidate rule
# ---------------------------------------------------------------------

def test_build_role_resolution_single_candidate():
    dreams = [_dream(["girlfriend Abby"]), _dream(["my girlfriend"])]
    resolution = identity.build_role_resolution(d["people"] for d in dreams)
    assert resolution["girlfriend"] == "abby"


def test_build_role_resolution_two_candidates_is_ambiguous():
    dreams = [_dream(["brother James"]), _dream(["brother Michael"])]
    resolution = identity.build_role_resolution(d["people"] for d in dreams)
    assert resolution["brother"] is None


def test_build_role_resolution_no_candidate_is_absent():
    dreams = [_dream(["my brother"])]
    resolution = identity.build_role_resolution(d["people"] for d in dreams)
    assert resolution.get("brother") is None


# ---------------------------------------------------------------------
# resolve_person_key / validate_person_aliases -- the real contract
# ---------------------------------------------------------------------

def test_validate_person_aliases_accepts_a_legitimate_merge():
    dreams = [_dream(["girlfriend Abby"]), _dream(["my girlfriend"])]
    valid = identity.validate_person_aliases("abby", ["abby", "girlfriend abby", "my girlfriend"], dreams, [])
    assert set(valid) == {"abby", "girlfriend abby", "my girlfriend"}


def test_validate_person_aliases_rejects_an_unrelated_alias():
    """The adversarial case the brief names directly: an unrelated alias
    must not be able to broaden evidence for a symbol it has nothing to
    do with."""
    dreams = [_dream(["Abby"])]
    valid = identity.validate_person_aliases("a door", ["abby", "mother", "anything at all"], dreams, [])
    assert valid == []


def test_validate_person_aliases_two_named_brothers_stay_separate():
    """Two different people with the same relationship role: an
    ambiguous bare mention must not be claimed for either one."""
    dreams = [_dream(["brother James"]), _dream(["brother Michael"]), _dream(["my brother"])]
    valid_for_james = identity.validate_person_aliases("james", ["my brother"], dreams, [])
    valid_for_michael = identity.validate_person_aliases("michael", ["my brother"], dreams, [])
    assert valid_for_james == []
    assert valid_for_michael == []


def test_validate_person_aliases_ambiguous_bare_role_with_no_named_candidate():
    dreams = [_dream(["my brother"])]
    valid = identity.validate_person_aliases("role:brother", ["my brother"], dreams, [])
    # "my brother" legitimately IS "role:brother" itself here (no named
    # candidate to merge into) -- this is the one case where the bucket
    # key is the correct target.
    assert valid == ["my brother"]


def test_validate_person_aliases_honors_an_explicit_merge_correction():
    """A saved person_identity_links 'merge' row lets an otherwise-
    ambiguous role resolve to a specific confirmed identity."""
    dreams = [_dream(["brother James"]), _dream(["brother Michael"]), _dream(["my brother"])]
    links = [{"subject_key": "role:brother", "decision": "merge", "target_key": "james"}]
    valid = identity.validate_person_aliases("james", ["my brother"], dreams, links)
    assert valid == ["my brother"]
    # Michael is never touched by this correction.
    valid_michael = identity.validate_person_aliases("michael", ["my brother"], dreams, links)
    assert valid_michael == []


def test_validate_person_aliases_honors_an_explicit_separate_correction():
    """Forced separation: even with exactly one named candidate, an
    explicit 'separate' correction must override the automatic merge."""
    dreams = [_dream(["girlfriend Abby"]), _dream(["my girlfriend"])]
    links = [{"subject_key": "role:girlfriend", "decision": "separate"}]
    valid = identity.validate_person_aliases("abby", ["my girlfriend"], dreams, links)
    assert valid == []
    valid_bucket = identity.validate_person_aliases("role:girlfriend", ["my girlfriend"], dreams, links)
    assert valid_bucket == ["my girlfriend"]


def test_validate_person_aliases_rejects_a_stale_alias_after_separation():
    """A client that hasn't refreshed its own identity-link cache (or a
    deliberately stale/replayed request) might still send an alias that
    WAS valid before a correction, but no longer is -- the server must
    judge by its own current data, not accept a once-true claim."""
    dreams = [_dream(["girlfriend Abby"]), _dream(["my girlfriend"])]
    # Before any correction: "my girlfriend" legitimately resolves to "abby".
    assert identity.validate_person_aliases("abby", ["my girlfriend"], dreams, []) == ["my girlfriend"]
    # After a 'separate' correction is saved: the exact same alias,
    # sent the exact same way, is no longer accepted.
    links = [{"subject_key": "role:girlfriend", "decision": "separate"}]
    assert identity.validate_person_aliases("abby", ["my girlfriend"], dreams, links) == []


def test_validate_person_aliases_bounds_and_malformed_input_do_not_crash():
    dreams = [_dream(["Abby"])]
    assert identity.validate_person_aliases("abby", [], dreams, []) == []
    assert identity.validate_person_aliases("abby", None, dreams, []) == []
    assert identity.validate_person_aliases("abby", ["", "   ", None, 123, ["x"]], dreams, []) == []
    # Malformed dream/link rows don't crash the validator either.
    assert identity.validate_person_aliases("abby", ["abby"], [{"people": None}, {}], []) == ["abby"]
    assert identity.validate_person_aliases("abby", ["abby"], dreams, [{}, {"subject_key": ""}, None]) == ["abby"]


def test_validate_person_aliases_duplicate_alias_strings_only_counted_once_logically():
    dreams = [_dream(["Abby"])]
    valid = identity.validate_person_aliases("abby", ["Abby", "ABBY", "abby"], dreams, [])
    # All three normalize to the same valid alias -- returned once per
    # input entry (the caller only ever uses this as a set), not
    # deduplicated here, but every entry is individually correct.
    assert valid == ["abby", "abby", "abby"]


# ---------------------------------------------------------------------
# Stage 8 Phase B.2 Priority 3 -- documents a real, UNFIXED limitation
# of the current data model (deliberately not implemented this phase;
# see the Phase B.2 completion report's "per-dream identity" section
# for the proposed schema and why building it was deferred for review
# rather than shipped here). person_identity_links has no notion of
# "this one dream" -- a correction is keyed only by role pattern
# ("role:brother") or resolved name, account-wide. This test exists so
# that limitation is demonstrated and pinned down by a fixture, not
# just asserted in a comment: if person_identity_links ever gains
# per-dream scoping, this test's own expectations should change to
# match, which is exactly the signal that the limitation was resolved.
# ---------------------------------------------------------------------

def test_priority_3_a_global_merge_correction_cannot_distinguish_two_dreams_different_brothers():
    """The brief's own example: Dream A's bare 'my brother' is really
    about James; Dream B's bare 'my brother' is really about a
    DIFFERENT person the account has never named anywhere else, so
    nothing in the data distinguishes it from Dream A's. Confirming
    'Same as James?' for the ambiguous role:brother bucket -- the only
    correction granularity the schema currently supports -- necessarily
    applies to BOTH dreams' bare mentions identically. This is not a
    bug to fix with a smarter rule: with only an account-wide
    person_identity_links row to express the correction, there is no
    way to tell these two dreams apart without a per-dream mechanism
    (not built this phase -- see the completion report)."""
    dream_a_about_james = _dream(["my brother"])
    dream_b_about_someone_else = _dream(["my brother"])
    dreams = [dream_a_about_james, dream_b_about_someone_else]

    # Before any correction, both are correctly left ambiguous -- not
    # claimed for anyone. This part the deterministic rules already get
    # right (see test_validate_person_aliases_two_named_brothers_stay_separate).
    assert identity.validate_person_aliases("role:brother", ["my brother"], dreams, []) == ["my brother"]

    # Once the person confirms "Same as James?" for the role:brother
    # bucket (the UI's only available action for an ambiguous role --
    # see index.html's renderLoomPreviewIdentitySection), the resulting
    # person_identity_links row is account-wide by construction.
    links = [{"subject_key": "role:brother", "decision": "merge", "target_key": "james"}]

    # Both dreams' bare mentions now resolve to "james" identically --
    # including Dream B's, which may genuinely be about someone else.
    # This is the documented, known limitation, not a surprise: the UI
    # warns about it before the person confirms (see
    # renderLoomPreviewIdentitySection's "applies to every ... mention
    # across your whole journal" copy), and the correction stays fully
    # reversible via the existing DELETE /people/identity-links path.
    assert identity.validate_person_aliases("james", ["my brother"], dreams, links) == ["my brother"]
    # The SAME alias, from the SAME two otherwise-indistinguishable
    # dreams, validates for "james" regardless of which dream it came
    # from -- there is no per-dream signal in this data model to tell
    # Dream A's mention from Dream B's.
