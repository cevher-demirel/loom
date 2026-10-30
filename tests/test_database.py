"""
tests/test_database.py -- unit tests for database.py: account creation,
login, and dream CRUD, with a particular focus on the ownership checks
(every dream function is scoped to a user_id) since that's the one bug
category here that would actually be a privacy incident if it broke --
one person reading, editing, or deleting another person's dreams.
"""

import database


FAKE_EXTRACTED = {
    "symbols": ["a door"],
    "emotions": ["curiosity"],
    "people": [],
    "settings": ["a hallway"],
    "themes": ["transition"],
    "symbol_icons": {"a door": "door"},
}


# --- Accounts --------------------------------------------------------------

def test_create_user_returns_account_with_token(fresh_db):
    user = database.create_user("alice", "alice@example.com", "hunter22")
    assert user["username"] == "alice"
    assert "token" in user and user["token"]
    assert isinstance(user["id"], int)


def test_create_user_duplicate_username_raises(fresh_db):
    database.create_user("alice", "", "hunter22")
    try:
        database.create_user("alice", "", "different-password")
        assert False, "expected ValueError for a duplicate username"
    except ValueError:
        pass


def test_authenticate_user_wrong_password_returns_none(fresh_db):
    database.create_user("alice", "", "hunter22")
    assert database.authenticate_user("alice", "wrong-password") is None


def test_authenticate_user_correct_password_returns_fresh_token(fresh_db):
    created = database.create_user("alice", "", "hunter22")
    logged_in = database.authenticate_user("alice", "hunter22")
    assert logged_in is not None
    assert logged_in["id"] == created["id"]
    # Every login issues a brand-new token rather than reusing the old
    # one -- an old leaked token shouldn't still work after logging in
    # again elsewhere.
    assert logged_in["token"] != created["token"]


def test_get_user_by_token_invalid_token_returns_none(fresh_db):
    assert database.get_user_by_token("not-a-real-token") is None
    assert database.get_user_by_token(None) is None


def test_get_user_by_token_valid_token_resolves(fresh_db):
    user = database.create_user("alice", "", "hunter22")
    resolved = database.get_user_by_token(user["token"])
    assert resolved is not None
    assert resolved["id"] == user["id"]
    assert resolved["username"] == "alice"


def test_clear_token_invalidates_it(fresh_db):
    user = database.create_user("alice", "", "hunter22")
    database.clear_token(user["id"])
    assert database.get_user_by_token(user["token"]) is None


# --- Dream CRUD --------------------------------------------------------------

def test_insert_and_get_dream_round_trip(fresh_db):
    user = database.create_user("alice", "", "hunter22")
    dream_id = database.insert_dream(
        user["id"], "I was flying over my hometown.", FAKE_EXTRACTED,
        "A reading about freedom.", [0.1, 0.2, 0.3],
    )
    dream = database.get_dream(user["id"], dream_id)
    assert dream is not None
    assert dream["raw_text"] == "I was flying over my hometown."
    assert dream["symbols"] == ["a door"]
    assert dream["symbol_icons"] == {"a door": "door"}
    assert dream["interpretation"] == "A reading about freedom."
    assert dream["embedding"] == [0.1, 0.2, 0.3]
    assert dream["conversation"] == []


def test_update_dream_overwrites_text_and_clears_conversation(fresh_db):
    user = database.create_user("alice", "", "hunter22")
    dream_id = database.insert_dream(
        user["id"], "original text", FAKE_EXTRACTED, "original reading", [0.1],
    )
    database.update_dream_conversation(
        user["id"], dream_id, [{"role": "user", "content": "more context"}]
    )

    updated = database.update_dream(
        user["id"], dream_id, "edited text", FAKE_EXTRACTED, "new reading", [0.9],
    )
    assert updated is True

    dream = database.get_dream(user["id"], dream_id)
    assert dream["raw_text"] == "edited text"
    assert dream["interpretation"] == "new reading"
    # An edit invalidates the old conversation -- it was grounded in the
    # text and reading that no longer exist.
    assert dream["conversation"] == []


def test_update_symbol_icons_leaves_everything_else_untouched(fresh_db):
    # Simulates a dream logged before the symbol_icons column existed:
    # insert it with none, then backfill just symbols/symbol_icons (what
    # backfill_symbol_icons.py does) and confirm text, interpretation,
    # and conversation are all untouched.
    user = database.create_user("alice", "", "hunter22")
    dream_id = database.insert_dream(
        user["id"], "original text", FAKE_EXTRACTED, "original reading", [0.1],
    )
    database.update_dream_conversation(
        user["id"], dream_id, [{"role": "user", "content": "a follow-up"}]
    )

    database.update_symbol_icons(
        user["id"], dream_id, ["a hot tub", "my brother"], {"a hot tub": "water", "my brother": "people"},
    )

    dream = database.get_dream(user["id"], dream_id)
    assert dream["symbols"] == ["a hot tub", "my brother"]
    assert dream["symbol_icons"] == {"a hot tub": "water", "my brother": "people"}
    assert dream["raw_text"] == "original text"
    assert dream["interpretation"] == "original reading"
    assert dream["conversation"] == [{"role": "user", "content": "a follow-up"}]


def test_update_embedding_only_changes_embedding(fresh_db):
    user = database.create_user("alice", "", "hunter22")
    dream_id = database.insert_dream(
        user["id"], "original text", FAKE_EXTRACTED, "original reading", [0.1],
    )
    database.update_embedding(user["id"], dream_id, [9.9, 9.9])
    dream = database.get_dream(user["id"], dream_id)
    assert dream["embedding"] == [9.9, 9.9]
    assert dream["raw_text"] == "original text"
    assert dream["interpretation"] == "original reading"


def test_delete_dream_removes_it(fresh_db):
    user = database.create_user("alice", "", "hunter22")
    dream_id = database.insert_dream(
        user["id"], "a dream to delete", FAKE_EXTRACTED, "reading", [0.1],
    )
    assert database.delete_dream(user["id"], dream_id) is True
    assert database.get_dream(user["id"], dream_id) is None


def test_delete_dream_nonexistent_returns_false(fresh_db):
    user = database.create_user("alice", "", "hunter22")
    assert database.delete_dream(user["id"], 99999) is False


def test_get_all_dreams_oldest_first(fresh_db):
    user = database.create_user("alice", "", "hunter22")
    first_id = database.insert_dream(user["id"], "first", FAKE_EXTRACTED, "r1", [0.1])
    second_id = database.insert_dream(user["id"], "second", FAKE_EXTRACTED, "r2", [0.2])
    dreams = database.get_all_dreams(user["id"])
    assert [d["id"] for d in dreams] == [first_id, second_id]


# --- Ownership isolation -- the privacy-critical part -----------------------

def test_user_cannot_read_another_users_dream(fresh_db):
    alice = database.create_user("alice", "", "hunter22")
    bob = database.create_user("bob", "", "hunter22")
    dream_id = database.insert_dream(alice["id"], "alice's secret dream", FAKE_EXTRACTED, "r", [0.1])

    assert database.get_dream(bob["id"], dream_id) is None
    # But the owner can still read it, same id.
    assert database.get_dream(alice["id"], dream_id) is not None


def test_user_cannot_edit_another_users_dream(fresh_db):
    alice = database.create_user("alice", "", "hunter22")
    bob = database.create_user("bob", "", "hunter22")
    dream_id = database.insert_dream(alice["id"], "alice's dream", FAKE_EXTRACTED, "r", [0.1])

    updated = database.update_dream(bob["id"], dream_id, "bob's rewrite", FAKE_EXTRACTED, "bob's reading", [0.2])
    assert updated is False
    # Alice's dream is untouched.
    assert database.get_dream(alice["id"], dream_id)["raw_text"] == "alice's dream"


def test_user_cannot_delete_another_users_dream(fresh_db):
    alice = database.create_user("alice", "", "hunter22")
    bob = database.create_user("bob", "", "hunter22")
    dream_id = database.insert_dream(alice["id"], "alice's dream", FAKE_EXTRACTED, "r", [0.1])

    assert database.delete_dream(bob["id"], dream_id) is False
    # Still there, still readable by its real owner.
    assert database.get_dream(alice["id"], dream_id) is not None


def test_get_all_dreams_only_returns_own_dreams(fresh_db):
    alice = database.create_user("alice", "", "hunter22")
    bob = database.create_user("bob", "", "hunter22")
    database.insert_dream(alice["id"], "alice's dream", FAKE_EXTRACTED, "r", [0.1])
    database.insert_dream(bob["id"], "bob's dream", FAKE_EXTRACTED, "r", [0.1])

    alice_dreams = database.get_all_dreams(alice["id"])
    assert len(alice_dreams) == 1
    assert alice_dreams[0]["raw_text"] == "alice's dream"


# --- Health ------------------------------------------------------------------

def test_ping_returns_true_on_a_working_database(fresh_db):
    assert database.ping() is True


# --- Personal meanings -------------------------------------------------------

def test_save_personal_meaning_round_trip(fresh_db):
    alice = database.create_user("alice", "", "hunter22")
    saved = database.save_personal_meaning(
        alice["id"], "symbol", "water", "Water",
        "Water reminds me of moving to a new city.", "noted after a recurring dream",
    )
    assert saved["meaning"] == "Water reminds me of moving to a new city."

    fetched = database.get_personal_meaning(alice["id"], "symbol", "water")
    assert fetched["subject_label"] == "Water"
    assert fetched["note"] == "noted after a recurring dream"


def test_save_personal_meaning_twice_preserves_created_at_but_updates_meaning(fresh_db):
    alice = database.create_user("alice", "", "hunter22")
    first = database.save_personal_meaning(alice["id"], "symbol", "water", "Water", "First take.")
    second = database.save_personal_meaning(alice["id"], "symbol", "water", "Water", "Revised take.")

    assert second["created_at"] == first["created_at"]
    assert second["meaning"] == "Revised take."
    assert database.list_personal_meanings(alice["id"]) == [second]


def test_delete_personal_meaning_removes_it(fresh_db):
    alice = database.create_user("alice", "", "hunter22")
    database.save_personal_meaning(alice["id"], "symbol", "water", "Water", "Means something.")
    database.delete_personal_meaning(alice["id"], "symbol", "water")
    assert database.get_personal_meaning(alice["id"], "symbol", "water") is None


def test_personal_meanings_are_scoped_per_user(fresh_db):
    alice = database.create_user("alice", "", "hunter22")
    bob = database.create_user("bob", "", "hunter22")
    database.save_personal_meaning(alice["id"], "symbol", "water", "Water", "Alice's take.")

    assert database.get_personal_meaning(bob["id"], "symbol", "water") is None
    assert database.list_personal_meanings(bob["id"]) == []


# --- Connection feedback ------------------------------------------------------

def test_save_connection_feedback_round_trip(fresh_db):
    alice = database.create_user("alice", "", "hunter22")
    saved = database.save_connection_feedback(
        alice["id"], "symbol:water|symbol:anxiety", "relevant",
    )
    assert saved["status"] == "relevant"
    assert database.get_connection_feedback(alice["id"], "symbol:water|symbol:anxiety")["status"] == "relevant"


def test_save_connection_feedback_twice_updates_status_not_history(fresh_db):
    alice = database.create_user("alice", "", "hunter22")
    first = database.save_connection_feedback(alice["id"], "symbol:water|symbol:anxiety", "relevant")
    second = database.save_connection_feedback(alice["id"], "symbol:water|symbol:anxiety", "not_relevant", "actually unrelated")

    assert second["created_at"] == first["created_at"]
    assert second["status"] == "not_relevant"
    assert database.list_connection_feedback(alice["id"]) == [second]


def test_delete_account_also_clears_personal_meanings_and_connection_feedback(fresh_db):
    alice = database.create_user("alice", "", "hunter22")
    database.save_personal_meaning(alice["id"], "symbol", "water", "Water", "Means something.")
    database.save_connection_feedback(alice["id"], "symbol:water|symbol:anxiety", "relevant")

    database.delete_account(alice["id"])

    assert database.get_personal_meaning(alice["id"], "symbol", "water") is None
    assert database.get_connection_feedback(alice["id"], "symbol:water|symbol:anxiety") is None


# --- Element interpretations (Stage 11) ---------------------------------------

def test_save_element_interpretation_round_trip(fresh_db):
    alice = database.create_user("alice", "", "hunter22")
    saved = database.save_element_interpretation(
        alice["id"], "a door", "A Door",
        "A short teaser.", "General symbolic reading.", "Journal-grounded reading.",
        "How did it feel?", 3, "2025-06-10",
    )
    assert saved["symbol_label"] == "A Door"
    assert saved["general_text"] == "General symbolic reading."
    assert saved["occurrence_count"] == 3

    fetched = database.get_element_interpretation(alice["id"], "a door")
    assert fetched["journal_text"] == "Journal-grounded reading."
    assert fetched["latest_occurrence_date"] == "2025-06-10"


def test_save_element_interpretation_stores_occurrence_fingerprint(fresh_db):
    """Stage 11.1: the content fingerprint main.py now checks instead of
    (or alongside) occurrence_count/latest_occurrence_date."""
    alice = database.create_user("alice", "", "hunter22")
    database.save_element_interpretation(
        alice["id"], "a door", "A Door", "t", "g", "j", "d", 1, "2025-06-01",
        occurrence_fingerprint="abc123",
    )
    fetched = database.get_element_interpretation(alice["id"], "a door")
    assert fetched["occurrence_fingerprint"] == "abc123"


def test_save_element_interpretation_without_fingerprint_defaults_to_empty_string(fresh_db):
    """A caller that doesn't pass occurrence_fingerprint (an old direct
    caller, or a row saved before this column meant anything) must still
    work -- it just reads back as '', which main.py treats as unknown/
    stale rather than a real match. See get_element_interpretation's
    staleness check in main.py's symbol_insight handler."""
    alice = database.create_user("alice", "", "hunter22")
    database.save_element_interpretation(
        alice["id"], "a door", "A Door", "t", "g", "j", "d", 1, "2025-06-01",
    )
    fetched = database.get_element_interpretation(alice["id"], "a door")
    assert fetched["occurrence_fingerprint"] == ""


def test_save_element_interpretation_twice_overwrites_without_history(fresh_db):
    alice = database.create_user("alice", "", "hunter22")
    database.save_element_interpretation(
        alice["id"], "a door", "A Door", "T1", "G1", "J1", "D1", 1, "2025-06-01",
    )
    second = database.save_element_interpretation(
        alice["id"], "a door", "A Door", "T2", "G2", "J2", "D2", 2, "2025-06-10",
    )
    assert second["general_text"] == "G2"
    assert database.get_element_interpretation(alice["id"], "a door")["general_text"] == "G2"


def test_element_interpretations_are_scoped_per_user(fresh_db):
    alice = database.create_user("alice", "", "hunter22")
    bob = database.create_user("bob", "", "hunter22")
    database.save_element_interpretation(
        alice["id"], "a door", "A Door", "T", "G", "J", "D", 1, "2025-06-01",
    )
    assert database.get_element_interpretation(bob["id"], "a door") is None


def test_delete_account_also_clears_element_interpretations(fresh_db):
    alice = database.create_user("alice", "", "hunter22")
    database.save_element_interpretation(
        alice["id"], "a door", "A Door", "T", "G", "J", "D", 1, "2025-06-01",
    )
    database.delete_account(alice["id"])
    assert database.get_element_interpretation(alice["id"], "a door") is None
