"""
tests/test_stage12_concepts.py -- Stage 12 "ONE CONCEPT, ONE NODE":
concept normalization, unique-dream aggregation, interpretation-cache
collision avoidance, and personal-meaning preservation across a
consolidated concept's legacy wordings.

Map-node consolidation, connection recalculation, and related-dreams
de-duplication themselves live entirely in index.html's
collectDreamElements/computeElementCounts/computeDiscoveries (there is
no dedicated backend endpoint for Map data -- see Part 1's data-flow
trace in the Stage 12 final report), so those are covered by the
Playwright synthetic-dataset check (Part 19) rather than here. This
file covers everything that does live in main.py: concept_slug_for /
concept_key_for / concept_display_label_for themselves, and the three
backend surfaces Part 13/14 call out as collision-prone --
/symbols/insight's interpretation cache, /symbols/chat's thread, and
occurrence lookup across aliased wordings.
"""

import pytest

import database
import engine
import main

from tests.test_main import FAKE_EXTRACTED, client, mock_engine, _signup, _auth_headers, _interpret_result


# --- A. Concept normalization -----------------------------------------------

@pytest.mark.parametrize("category,raw,expected_slug", [
    ("person", "My brother", "brother"),
    ("person", "brother", "brother"),
    ("person", "Brother", "brother"),
    ("person", "My mom", "mother"),
    ("person", "Mom", "mother"),
    ("person", "Mother", "mother"),
    ("person", "My mother", "mother"),
    ("person", "My dad", "father"),
    ("person", "Dad", "father"),
    ("person", "Father", "father"),
    ("person", "My father", "father"),
    ("person", "My girlfriend", "girlfriend"),
    ("person", "My girlfriend Abby", "girlfriend"),
    ("person", "My friend", "friend"),
    ("person", "Friend", "friend"),
    ("symbol", "A door", "door"),
    ("symbol", "door", "door"),
    ("symbol", "The door", "door"),
    ("symbol", "Door", "door"),
])
def test_concept_slug_for_merges_expected_aliases(category, raw, expected_slug):
    assert main.concept_slug_for(category, raw) == expected_slug


@pytest.mark.parametrize("category,a,b", [
    ("person", "Brother", "Brother-in-law"),
    ("person", "Father", "Father figure"),
    ("person", "Mother", "Mother Nature"),
    ("person", "Girlfriend", "Wife"),
    ("person", "Boyfriend", "Husband"),
    ("person", "My girlfriend", "my girlfriend's sister"),
    ("emotion", "Fear", "Anxiety"),
    ("place", "House", "Home"),
    ("symbol", "Car", "Camper van"),
    ("symbol", "Door", "Doorway"),
])
def test_concept_slug_for_keeps_exclusions_distinct(category, a, b):
    assert main.concept_slug_for(category, a) != main.concept_slug_for(category, b)


def test_concept_slug_for_unknown_label_stays_itself():
    # Not in any alias table -- a brand new, never-seen label must keep
    # working without any manual configuration (Part 5's "unknown labels
    # should continue to work without manual configuration").
    assert main.concept_slug_for("person", "My coworker Dave") == "my coworker dave"
    assert main.concept_slug_for("symbol", "a lighthouse") == "lighthouse"


def test_concept_key_for_is_category_aware_and_collision_safe():
    # Part 4's central example: a person called Door must not share an
    # identifier with the symbol Door.
    assert main.concept_key_for("person", "Door") == "person:door"
    assert main.concept_key_for("symbol", "Door") == "symbol:door"
    assert main.concept_key_for("person", "Door") != main.concept_key_for("symbol", "Door")


def test_concept_display_label_for_person_and_symbol():
    assert main.concept_display_label_for("person", "my brother") == "Brother"
    assert main.concept_display_label_for("person", "brother") == "Brother"
    assert main.concept_display_label_for("person", "my coworker dave") == "My coworker dave"  # unmatched: cosmetic capitalization only
    assert main.concept_display_label_for("symbol", "a door") == "Door"
    assert main.concept_display_label_for("symbol", "door") == "Door"
    assert main.concept_display_label_for("emotion", "fear") == "fear"  # unchanged, as recorded


# --- B/D. Unique-dream occurrence aggregation across aliased wordings ------

def test_concept_occurrences_merges_differently_worded_mentions(fresh_db, mock_engine, monkeypatch):
    """Dream 1 mentions "my brother", Dream 2 mentions "brother" -- both
    must count toward the one consolidated "person:brother" concept, and
    a dream mentioning both must still only appear once (Part 6: "Brother
    appears in 12 unique dreams, not 14")."""
    user = _signup()

    def extract_with(people):
        return lambda raw_text, emotions_reported=None: dict(FAKE_EXTRACTED, people=people, symbols=[], symbol_icons={})

    monkeypatch.setattr(engine, "extract_dream_data", extract_with(["my brother"]))
    client.post("/interpret", json={"raw_text": "a dream about my brother"}, headers=_auth_headers(user["token"]))
    monkeypatch.setattr(engine, "extract_dream_data", extract_with(["brother"]))
    client.post("/interpret", json={"raw_text": "a dream about brother"}, headers=_auth_headers(user["token"]))
    monkeypatch.setattr(engine, "extract_dream_data", extract_with(["my brother", "brother"]))
    client.post("/interpret", json={"raw_text": "a dream about both my brother and brother"}, headers=_auth_headers(user["token"]))

    occurrences = main._concept_occurrences(user["id"], "person", "person:brother")
    # Three dreams fed the concept, but the third dream's own two
    # mentions must not double it up -- exactly 3 occurrences, not 4.
    assert len(occurrences) == 3


def test_concept_occurrences_symbol_merges_article_variants(fresh_db, mock_engine, monkeypatch):
    user = _signup()

    def extract_with(symbols):
        return lambda raw_text, emotions_reported=None: dict(
            FAKE_EXTRACTED, symbols=symbols, symbol_icons={s: "door" for s in symbols}, themes=[],
        )

    monkeypatch.setattr(engine, "extract_dream_data", extract_with(["a door"]))
    client.post("/interpret", json={"raw_text": "walked through a door"}, headers=_auth_headers(user["token"]))
    monkeypatch.setattr(engine, "extract_dream_data", extract_with(["door"]))
    client.post("/interpret", json={"raw_text": "the door was locked"}, headers=_auth_headers(user["token"]))
    monkeypatch.setattr(engine, "extract_dream_data", extract_with(["The door"]))
    client.post("/interpret", json={"raw_text": "the door opened on its own"}, headers=_auth_headers(user["token"]))

    occurrences = main._concept_occurrences(user["id"], "symbol", "symbol:door")
    assert len(occurrences) == 3


def test_concept_occurrences_does_not_cross_categories(fresh_db, mock_engine, monkeypatch):
    """A person named Door and a symbol Door must never be treated as
    the same concept's occurrences."""
    user = _signup()
    monkeypatch.setattr(
        engine, "extract_dream_data",
        lambda raw_text, emotions_reported=None: dict(
            FAKE_EXTRACTED, people=["Door"], symbols=["a door"], symbol_icons={"a door": "door"},
        ),
    )
    client.post("/interpret", json={"raw_text": "Door the cat sat by a door"}, headers=_auth_headers(user["token"]))

    person_occ = main._concept_occurrences(user["id"], "person", "person:door")
    symbol_occ = main._concept_occurrences(user["id"], "symbol", "symbol:door")
    assert len(person_occ) == 1
    assert len(symbol_occ) == 1  # both real, both independent -- neither one missing nor doubled


# --- F. Interpretation-cache collision avoidance ----------------------------

def test_symbol_insight_shares_cache_across_aliased_wordings(fresh_db, mock_engine, monkeypatch):
    calls = []
    monkeypatch.setattr(
        engine, "symbol_insight",
        lambda symbol, occurrences, **kw: calls.append(1) or {"teaser": "t", "meaning": "g", "general": "g", "journal": "j", "direction": "d"},
    )
    user = _signup()
    monkeypatch.setattr(
        engine, "extract_dream_data",
        lambda raw_text, emotions_reported=None: dict(FAKE_EXTRACTED, people=["my brother"], symbols=[], symbol_icons={}),
    )
    client.post("/interpret", json={"raw_text": "a dream about my brother"}, headers=_auth_headers(user["token"]))

    r1 = client.post("/symbols/insight", json={"symbol": "my brother", "category": "person"}, headers=_auth_headers(user["token"]))
    assert r1.status_code == 200
    assert len(calls) == 1
    # Opened again from the consolidated Map node, under the concept's
    # own display label instead of the dream's original wording -- must
    # reuse the exact same cache row, not regenerate.
    r2 = client.post("/symbols/insight", json={"symbol": "Brother", "category": "person"}, headers=_auth_headers(user["token"]))
    assert r2.status_code == 200
    assert len(calls) == 1
    assert r2.json()["teaser"] == r1.json()["teaser"]


def test_symbol_insight_does_not_collide_across_categories(fresh_db, mock_engine, monkeypatch):
    calls = []
    monkeypatch.setattr(
        engine, "symbol_insight",
        lambda symbol, occurrences, **kw: calls.append(kw.get("category")) or {"teaser": "t-" + str(kw.get("category")), "meaning": "g", "general": "g", "journal": "j", "direction": "d"},
    )
    user = _signup()
    monkeypatch.setattr(
        engine, "extract_dream_data",
        lambda raw_text, emotions_reported=None: dict(
            FAKE_EXTRACTED, people=["Door"], symbols=["a door"], symbol_icons={"a door": "door"},
        ),
    )
    client.post("/interpret", json={"raw_text": "Door the cat sat by a door"}, headers=_auth_headers(user["token"]))

    r_person = client.post("/symbols/insight", json={"symbol": "Door", "category": "person"}, headers=_auth_headers(user["token"]))
    r_symbol = client.post("/symbols/insight", json={"symbol": "Door", "category": "symbol"}, headers=_auth_headers(user["token"]))
    assert len(calls) == 2  # two independent AI calls -- no shared cache row
    assert r_person.json()["teaser"] != r_symbol.json()["teaser"]


def test_symbol_chat_thread_does_not_collide_across_categories(fresh_db, mock_engine, monkeypatch):
    user = _signup()
    monkeypatch.setattr(
        engine, "extract_dream_data",
        lambda raw_text, emotions_reported=None: dict(
            FAKE_EXTRACTED, people=["Door"], symbols=["a door"], symbol_icons={"a door": "door"},
        ),
    )
    client.post("/interpret", json={"raw_text": "Door the cat sat by a door"}, headers=_auth_headers(user["token"]))
    monkeypatch.setattr(engine, "symbol_chat_reply", lambda *a, **kw: "a reply")

    client.post("/symbols/chat", json={"symbol": "Door", "category": "person", "message": "hi"}, headers=_auth_headers(user["token"]))
    person_thread = client.get("/symbols/chat?symbol=Door&category=person", headers=_auth_headers(user["token"])).json()
    symbol_thread = client.get("/symbols/chat?symbol=Door&category=symbol", headers=_auth_headers(user["token"])).json()
    assert len(person_thread["conversation"]) == 2  # the message just sent
    assert len(symbol_thread["conversation"]) == 0  # untouched -- a different concept entirely


# --- E. Personal Meaning preservation across legacy wordings ---------------

def test_personal_meanings_under_different_legacy_keys_both_survive(fresh_db, mock_engine):
    """Two meanings saved under different original wordings of the same
    real-world concept (before or without ever using the consolidated
    concept key) must both be preserved -- never merged, concatenated,
    or silently overwritten (Part 12)."""
    user = _signup()
    headers = _auth_headers(user["token"])

    client.put("/personal-meanings", json={
        "subject_type": "person", "subject_key": "my brother", "subject_label": "My brother",
        "meaning": "My brother reminds me of protection.",
    }, headers=headers)
    client.put("/personal-meanings", json={
        "subject_type": "person", "subject_key": "brother", "subject_label": "Brother",
        "meaning": "Brother represents rivalry.",
    }, headers=headers)

    rows = client.get("/personal-meanings", headers=headers).json()
    person_rows = [r for r in rows if r["subject_type"] == "person"]
    assert len(person_rows) == 2
    meanings = {r["subject_key"]: r["meaning"] for r in person_rows}
    assert meanings["my brother"] == "My brother reminds me of protection."
    assert meanings["brother"] == "Brother represents rivalry."

    # Editing/removing the consolidated concept's own entry must not
    # touch the legacy one.
    client.delete("/personal-meanings/person/brother", headers=headers)
    rows_after = client.get("/personal-meanings", headers=headers).json()
    remaining_keys = {r["subject_key"] for r in rows_after if r["subject_type"] == "person"}
    assert remaining_keys == {"my brother"}
