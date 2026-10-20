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
