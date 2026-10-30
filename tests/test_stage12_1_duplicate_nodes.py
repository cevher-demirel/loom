"""
tests/test_stage12_1_duplicate_nodes.py -- Stage 12.1: production
correction for the duplicate-Brother-node bug reported from a real
iPhone after Stage 12 shipped.

Root cause (see main.py's _symbol_is_kinship_concept / index.html's
canonicalElementFor for the full comment): Stage 12 trusted the EXTRACTED
FIELD a mention came from (dream.people vs dream.symbols) as part of the
concept's identity ("symbol:brother" vs "person:brother"). That field is
a per-dream judgment call engine.extract_dream_data makes fresh every
time -- its own instructions only forbid duplicating a person already in
`people` WITHIN one dream's own `symbols` list, nothing stops a
DIFFERENT dream's independent extraction from classifying a bare
kinship word like "brother" as a symbol instead of a person. So the same
real concept could end up split across two catKeys even though both
display as "Brother" -- exactly the two visually-identical Map nodes in
the production screenshot.

This file covers the backend half of the fix (_symbol_is_kinship_concept,
_category_field_values reclassification, the "the "-stripping widening,
and the legacy chat-thread read-time fallback). Map-node consolidation
itself (collectDreamTags/collectDreamElements/canonicalElementFor) is
covered by the Playwright synthetic-dataset reproduction (Part 13), same
split as test_stage12_concepts.py uses for Stage 12.
"""

import pytest

import database
import engine
import main

from tests.test_main import FAKE_EXTRACTED, client, mock_engine, _signup, _auth_headers


# --- A. _symbol_is_kinship_concept: the exact, narrow whitelist -------------

@pytest.mark.parametrize("raw_label,expected_display", [
    ("brother", "Brother"),
    ("Brother", "Brother"),
    ("my brother", "Brother"),
    ("the brother", "Brother"),
    ("MY BROTHER", "Brother"),
    ("mom", "Mother"),
    ("mother", "Mother"),
    ("dad", "Father"),
    ("girlfriend", "Girlfriend"),
    ("girlfriend abby", "Girlfriend"),
    ("friend", "Friend"),
    ("best friend", "Friend"),
])
def test_symbol_is_kinship_concept_matches_whitelist(raw_label, expected_display):
    assert main._symbol_is_kinship_concept(raw_label) == expected_display


@pytest.mark.parametrize("raw_label", [
    "door", "a door", "the door", "doorway",  # Part 3: Door must never be treated as a person
    "brother-in-law", "brotherhood", "my brother's house", "older brother",
    "father figure", "mother nature", "her brother", "your brother",
])
def test_symbol_is_kinship_concept_leaves_everything_else_alone(raw_label):
    assert main._symbol_is_kinship_concept(raw_label) is None


def test_concept_slug_for_person_strips_leading_the_too():
    # Part 4's required mapping: "the brother" -> person:brother, same as
    # "my brother"/"brother".
    assert main.concept_slug_for("person", "the brother") == "brother"
    assert main.concept_key_for("person", "the brother") == "person:brother"
    assert main.concept_display_label_for("person", "the brother") == "Brother"


# --- B. _category_field_values: reclassification, not duplication ----------

def test_category_field_values_moves_kinship_symbol_into_person():
    dream = {
        "symbols": ["brother", "a door"], "themes": [], "people": [], "settings": [], "emotions": [],
    }
    assert main._category_field_values(dream, "person") == ["brother"]
    # The genuine symbol stays a symbol; the kinship word is excluded so
    # it's not ALSO counted as a symbol occurrence (no double-grounding).
    assert main._category_field_values(dream, "symbol") == ["a door"]


def test_category_field_values_combines_real_person_field_and_kinship_symbol():
    dream = {
        "symbols": ["brother"], "themes": [], "people": ["my brother"], "settings": [], "emotions": [],
    }
    values = main._category_field_values(dream, "person")
    assert values == ["my brother", "brother"]
    # Both resolve to the same concept key -- the caller (_concept_occurrences)
    # only cares about the dream matching once, not about this list's length.
    assert {main.concept_key_for("person", v) for v in values} == {"person:brother"}


def test_category_field_values_door_symbol_never_moves_to_person():
    dream = {
        "symbols": ["a door"], "themes": [], "people": ["Door"], "settings": [], "emotions": [],
    }
    assert main._category_field_values(dream, "symbol") == ["a door"]
    assert main._category_field_values(dream, "person") == ["Door"]


# --- C. End-to-end reproduction: the real production scenario --------------

def test_concept_occurrences_merges_dreams_regardless_of_which_field_brother_landed_in(fresh_db, mock_engine, monkeypatch):
    """Reproduces the exact production bug: Dream 1 has "my brother" in
    `people` (what Stage 12 already consolidated correctly); Dream 2 has
    the bare word "brother" mis-extracted into `symbols` instead (what
    Stage 12 missed, per Part 2's investigation). Before the Stage 12.1
    fix this would produce two separate concepts/nodes; after it, both
    dreams ground the single person:brother concept."""
    user = _signup()

    monkeypatch.setattr(
        engine, "extract_dream_data",
        lambda raw_text, emotions_reported=None: dict(FAKE_EXTRACTED, people=["my brother"], symbols=[], symbol_icons={}),
    )
    client.post("/interpret", json={"raw_text": "a dream about my brother"}, headers=_auth_headers(user["token"]))

    monkeypatch.setattr(
        engine, "extract_dream_data",
        lambda raw_text, emotions_reported=None: dict(
            FAKE_EXTRACTED, people=[], symbols=["brother"], symbol_icons={"brother": "person-standing"}, themes=[],
        ),
    )
    client.post("/interpret", json={"raw_text": "brother was there again"}, headers=_auth_headers(user["token"]))

    person_occurrences = main._concept_occurrences(user["id"], "person", "person:brother")
    assert len(person_occurrences) == 2  # both dreams ground the ONE concept

    # And the stray "symbol:brother" concept the pre-12.1 bug relied on
    # no longer independently exists -- it's been folded into person:brother.
    symbol_occurrences = main._concept_occurrences(user["id"], "symbol", "symbol:brother")
    assert symbol_occurrences == []


def test_symbol_insight_grounds_in_both_people_and_mis_extracted_symbol_dreams(fresh_db, mock_engine, monkeypatch):
    calls = []
    monkeypatch.setattr(
        engine, "symbol_insight",
        lambda symbol, occurrences, **kw: calls.append(len(occurrences)) or {"teaser": "t", "meaning": "g", "general": "g", "journal": "j", "direction": "d"},
    )
    user = _signup()
    monkeypatch.setattr(
        engine, "extract_dream_data",
        lambda raw_text, emotions_reported=None: dict(FAKE_EXTRACTED, people=["my brother"], symbols=[], symbol_icons={}),
    )
    client.post("/interpret", json={"raw_text": "a dream about my brother"}, headers=_auth_headers(user["token"]))
    monkeypatch.setattr(
        engine, "extract_dream_data",
        lambda raw_text, emotions_reported=None: dict(
            FAKE_EXTRACTED, people=[], symbols=["brother"], symbol_icons={"brother": "person-standing"}, themes=[],
        ),
    )
    client.post("/interpret", json={"raw_text": "brother again"}, headers=_auth_headers(user["token"]))

    r = client.post("/symbols/insight", json={"symbol": "Brother", "category": "person"}, headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    assert calls == [2]  # grounded in BOTH dreams, not just the one where it was in `people`


# --- D. Legacy chat-thread compatibility (Part 9) ---------------------------

def test_legacy_symbol_chat_thread_is_still_reachable_from_corrected_person_concept(fresh_db, mock_engine, monkeypatch):
    """Simulates a user who, before Stage 12.1 shipped, tapped the
    (buggy) "symbol:brother" node and had a real conversation there.
    After the fix, opening the person:brother concept must still surface
    those messages -- never lose them -- and continuing the conversation
    must save forward under the canonical key without touching the old
    row."""
    user = _signup()
    monkeypatch.setattr(
        engine, "extract_dream_data",
        lambda raw_text, emotions_reported=None: dict(
            FAKE_EXTRACTED, people=[], symbols=["brother"], symbol_icons={"brother": "person-standing"}, themes=[],
        ),
    )
    client.post("/interpret", json={"raw_text": "brother was there"}, headers=_auth_headers(user["token"]))

    # Simulate the pre-12.1 conversation directly in the DB, exactly as
    # the old (buggy) frontend would have saved it: under "symbol:brother".
    database.update_symbol_conversation(
        user["id"], "symbol:brother", "Brother",
        [{"role": "user", "content": "Why does he keep showing up?"}, {"role": "assistant", "content": "A reflection."}],
    )

    # The corrected concept must see that history, not an empty thread.
    r = client.get("/symbols/chat?symbol=Brother&category=person", headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    assert len(r.json()["conversation"]) == 2
    assert r.json()["conversation"][0]["content"] == "Why does he keep showing up?"

    # Continuing the conversation saves forward under the canonical key...
    monkeypatch.setattr(engine, "symbol_chat_reply", lambda *a, **kw: "a new reply")
    r2 = client.post(
        "/symbols/chat",
        json={"symbol": "Brother", "category": "person", "message": "Still thinking about it."},
        headers=_auth_headers(user["token"]),
    )
    assert r2.status_code == 200
    conversation = r2.json()["conversation"]
    assert len(conversation) == 4  # the 2 legacy messages, preserved in order, plus the new exchange
    assert conversation[0]["content"] == "Why does he keep showing up?"
    assert conversation[-1]["content"] == "a new reply"

    # ...and the original legacy row is untouched -- never deleted or
    # overwritten (Part 9/16).
    legacy_row = database.get_symbol_conversation(user["id"], "symbol:brother")
    assert len(legacy_row) == 2


def test_legacy_symbol_chat_fallback_never_crosses_into_unrelated_symbols(fresh_db, mock_engine, monkeypatch):
    """The legacy fallback is scoped to the closed kinship whitelist only
    -- a real, unrelated symbol conversation (e.g. Door) must never leak
    into a person concept that happens to share no relationship at all."""
    user = _signup()
    monkeypatch.setattr(
        engine, "extract_dream_data",
        lambda raw_text, emotions_reported=None: dict(
            FAKE_EXTRACTED, people=["Door"], symbols=["a door"], symbol_icons={"a door": "door"},
        ),
    )
    client.post("/interpret", json={"raw_text": "Door the cat sat by a door"}, headers=_auth_headers(user["token"]))
    database.update_symbol_conversation(
        user["id"], "symbol:door", "Door",
        [{"role": "user", "content": "about the real symbol door"}, {"role": "assistant", "content": "ok"}],
    )

    r = client.get("/symbols/chat?symbol=Door&category=person", headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    assert r.json()["conversation"] == []  # the person Door concept starts empty, as it should


def test_legacy_symbol_chat_fallback_does_not_override_an_existing_person_thread(fresh_db, mock_engine, monkeypatch):
    """If the canonical person:brother thread already has its own
    messages, the legacy symbol-keyed thread must not silently replace or
    prepend to it on every read (only used when the canonical key has
    nothing yet)."""
    user = _signup()
    monkeypatch.setattr(
        engine, "extract_dream_data",
        lambda raw_text, emotions_reported=None: dict(FAKE_EXTRACTED, people=["my brother"], symbols=[], symbol_icons={}),
    )
    client.post("/interpret", json={"raw_text": "a dream about my brother"}, headers=_auth_headers(user["token"]))

    database.update_symbol_conversation(
        user["id"], "person:brother", "Brother",
        [{"role": "user", "content": "the real, current thread"}, {"role": "assistant", "content": "ok"}],
    )
    database.update_symbol_conversation(
        user["id"], "symbol:brother", "Brother",
        [{"role": "user", "content": "an old, unrelated legacy thread"}, {"role": "assistant", "content": "ok"}],
    )

    r = client.get("/symbols/chat?symbol=Brother&category=person", headers=_auth_headers(user["token"]))
    conversation = r.json()["conversation"]
    assert len(conversation) == 2
    assert conversation[0]["content"] == "the real, current thread"
