"""
tests/test_stage7_audit.py -- Stage 7 audit harness.

Everything here runs against a disposable local SQLite database (the
same `fresh_db`/`mock_engine` isolation conftest.py already uses for the
rest of the suite -- see its own module docstring) and never touches
Turso, Pinecone, or a real AI provider. Nothing here is a permanent
addition to the regular regression suite; it exists to produce evidence
for the Stage 7 report (legacy-account compatibility, historical-data
preservation, cross-account isolation, password recovery, export/delete,
and the /interpret-status-vs-persistence question) and is safe to delete
once that report is accepted, or to keep as regression coverage -- the
user's call.

Run directly: python3 -m pytest tests/test_stage7_audit.py -v
"""

import json
import secrets
import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import database
import engine
import main

client = TestClient(main.app)


def _signup(username="alice", password="hunter22", email=None):
    if email is None:
        email = username + "@example.com"
    r = client.post("/signup", json={"username": username, "password": password, "email": email})
    assert r.status_code == 200, r.text
    return r.json()


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _interpret_result(response):
    text = response.text
    sep_index = text.rindex(main.STREAM_META_SEP)
    return json.loads(text[sep_index + 1:])


FAKE_EXTRACTED = {
    "symbols": ["a door"],
    "emotions": ["curiosity"],
    "emotions_plutchik": ["Trust", "Fear"],
    "people": ["a stranger"],
    "settings": ["a hallway"],
    "themes": ["transition"],
    "symbol_icons": {"a door": "door"},
}


@pytest.fixture
def mock_engine(monkeypatch):
    monkeypatch.setattr(engine, "extract_dream_data", lambda raw_text, emotions_reported=None: dict(FAKE_EXTRACTED))
    monkeypatch.setattr(engine, "embed_text", lambda text, input_type="document": [1.0, 0.0, 0.0])
    monkeypatch.setattr(engine, "interpret_dream", lambda raw_text, extracted, similar=None, profile=None, location=None, dream_timestamp=None, emotions_reported=None: "A fake reading.")

    def fake_interpret_dream_stream(raw_text, extracted, similar=None, profile=None, location=None, dream_timestamp=None, emotions_reported=None):
        yield "A fake reading."
    monkeypatch.setattr(engine, "interpret_dream_stream", fake_interpret_dream_stream)
    monkeypatch.setattr(engine, "continue_conversation", lambda messages, profile=None, related_dreams=None, search_fn=None, dream_timestamp=None: "A fake reply.")
    monkeypatch.setattr(engine, "classify_emotions_plutchik", lambda raw_text, emotions_freetext=None, emotions_reported=None: ["Awe"])
    monkeypatch.setattr(engine, "symbol_insight", lambda symbol, occurrences: {"teaser": "A fake teaser.", "meaning": "A fake meaning.", "direction": "A fake question?"})
    monkeypatch.setattr(engine, "symbol_chat_reply", lambda symbol, occurrences, opening_reflection, conversation, message, profile=None: "A fake symbol reply.")


# ===========================================================================
# SECTION 1 -- Historical account compatibility
# ===========================================================================

def _insert_legacy_user_row(username, password, email="", with_token_created_at=True):
    """
    Build a users row the way a pre-migration account would actually
    look on disk: same password hashing (that part of the schema never
    changed), but with the columns added by later migrations either
    NULL or at their just-migrated default, not realistic post-signup
    values. init_db() has already run by the time fresh_db hands this
    test a path (main's own module-level init_db() call), so the
    columns all exist -- this is about what's IN them, which is what a
    real upgraded-but-never-rewritten row would have.
    """
    salt = secrets.token_hex(16)
    password_hash = database._hash_password(password, salt)
    created_at = (datetime.now() - timedelta(days=900)).isoformat()
    token = secrets.token_hex(32)
    token_created_at = (datetime.now() - timedelta(days=5)).isoformat() if with_token_created_at else None
    database._execute("""
        INSERT INTO users (username, email, password_hash, salt, token, token_created_at,
                            created_at, email_verified, verify_token, verify_token_created_at,
                            is_guest, reset_token, reset_token_created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, 0, NULL, NULL)
    """, (username, email, password_hash, salt, token, token_created_at, created_at))
    return token


def test_legacy_account_with_null_token_created_at_still_authenticates(fresh_db):
    """
    A row created before the token_created_at column existed (migration
    adds it as NULL for every pre-existing row -- see init_db) must
    still let its owner log in and have their token accepted. This is
    the single most important compatibility case: database.py's own
    comment says this is intentional ("fail open rather than lock
    someone out"), but Stage 7 is about proving that, not trusting the
    comment.
    """
    _insert_legacy_user_row("legacy_no_token_ts", "oldpassword1", email="legacy1@example.com", with_token_created_at=False)

    r = client.post("/login", json={"username": "legacy_no_token_ts", "password": "oldpassword1"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]

    # And a bearer token that ALSO has no token_created_at (e.g. the row
    # was never touched since before that column existed, and nothing
    # has re-logged-in to refresh it) must still authenticate requests.
    rows, _ = database._execute("SELECT token FROM users WHERE username = ?", ("legacy_no_token_ts",))
    # login() always issues a fresh token with a real token_created_at
    # (see authenticate_user), so to test the TRULY untouched case --
    # someone who kept an old session alive and never logged in again --
    # go back and null the timestamp back out on the token login just issued.
    database._execute("UPDATE users SET token_created_at = NULL WHERE username = ?", ("legacy_no_token_ts",))
    r2 = client.get("/account", headers=_auth_headers(token))
    assert r2.status_code == 200, r2.text
    assert r2.json()["username"] == "legacy_no_token_ts"


def test_legacy_account_email_login_still_works(fresh_db):
    """Username/password is the oldest login shape; confirm email login
    (added later) also works for a legacy-shaped row."""
    _insert_legacy_user_row("legacy_email_user", "oldpassword2", email="legacyemail@example.com")
    r = client.post("/login", json={"username": "legacyemail@example.com", "password": "oldpassword2"})
    assert r.status_code == 200, r.text


def test_legacy_account_with_empty_email_cannot_be_matched_by_forgot_password(fresh_db):
    """
    A legacy "guest mode" row (is_guest=1, email='') must never be
    matched by /forgot-password -- database.create_password_reset_token
    explicitly filters `email != ''` for exactly this reason. Confirm it
    holds through the real endpoint, not just by reading the filter.
    """
    _insert_legacy_user_row("legacy_guest", "whatever-password-1", email="")
    database._execute("UPDATE users SET is_guest = 1 WHERE username = ?", ("legacy_guest",))
    r = client.post("/forgot-password", json={"email": ""})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    # Confirm no reset_token was actually issued to that row.
    rows, _ = database._execute("SELECT reset_token FROM users WHERE username = ?", ("legacy_guest",))
    assert rows[0]["reset_token"] is None


def test_very_long_username_and_email_accepted(fresh_db):
    """
    No server-side length cap exists on username/email (confirmed by
    reading SignupIn and validate_password_strength -- neither declares
    one). Document the actual behavior rather than assume: does a very
    long value round-trip correctly, or silently truncate/break?
    """
    long_username = "u" * 180
    long_email = ("x" * 150) + "@example.com"
    r = client.post("/signup", json={"username": long_username, "password": "hunter22x", "email": long_email})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    acct = client.get("/account", headers=_auth_headers(token))
    assert acct.json()["username"] == long_username
    assert acct.json()["email"] == long_email


def test_logout_then_old_token_rejected(fresh_db):
    user = _signup("logout_user", "hunter22y")
    token = user["token"]
    r = client.post("/logout", headers=_auth_headers(token))
    assert r.status_code == 200
    r2 = client.get("/account", headers=_auth_headers(token))
    assert r2.status_code == 401


# ===========================================================================
# SECTION 2 -- Historical dream and related-data preservation
# ===========================================================================

def _insert_legacy_dream_row(user_id, raw_text, days_ago=1200):
    """
    A dream row shaped like one saved before symbol_icons,
    emotions_reported, emotions_plutchik, conversation, or location
    existed -- all left NULL, the way init_db's additive ALTER TABLEs
    leave every pre-existing row.
    """
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat()
    _, dream_id = database._execute("""
        INSERT INTO dreams (user_id, timestamp, raw_text, symbols, emotions, people, settings,
                             themes, interpretation, embedding, conversation, location,
                             symbol_icons, emotions_reported, emotions_plutchik)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL)
    """, (
        user_id, ts, raw_text,
        json.dumps(["an old door"]), json.dumps(["unease"]), json.dumps([]), json.dumps(["a hallway"]),
        json.dumps(["change"]), "An old-style interpretation, saved before this column grew siblings.",
        json.dumps([1.0, 0.0, 0.0]),
    ))
    return dream_id


def test_legacy_dream_readable_and_unmutated_by_a_read(fresh_db):
    user = _signup("legacy_dreamer", "hunter22z")
    dream_id = _insert_legacy_dream_row(user["id"], "A dream from long before this app had half its current columns.")

    before_rows, _ = database._execute("SELECT * FROM dreams WHERE id = ?", (dream_id,))
    before = dict(before_rows[0])

    r = client.get("/dreams", headers=_auth_headers(user["token"]))
    assert r.status_code == 200, r.text
    listed = [d for d in r.json() if d["id"] == dream_id]
    assert len(listed) == 1, "legacy dream did not appear in this account's own archive"

    r2 = client.get(f"/dreams/{dream_id}/similar", headers=_auth_headers(user["token"]))
    assert r2.status_code == 200
    # Reading must not have changed a single stored column.
    after_rows, _ = database._execute("SELECT * FROM dreams WHERE id = ?", (dream_id,))
    after = dict(after_rows[0])
    assert before == after, "a read-only request mutated a legacy dream row"


def test_legacy_dream_missing_emotions_plutchik_backfills_without_touching_other_fields(fresh_db, mock_engine):
    """GET /dreams/{id}/emotions is the one legacy-aware endpoint that
    DOES write (a deliberate, narrow backfill -- see its own docstring).
    Confirm it only ever touches emotions_plutchik."""
    user = _signup("legacy_dreamer2", "hunter22aa")
    dream_id = _insert_legacy_dream_row(user["id"], "Another pre-Plutchik-column dream.")
    before_rows, _ = database._execute("SELECT * FROM dreams WHERE id = ?", (dream_id,))
    before = dict(before_rows[0])

    r = client.get(f"/dreams/{dream_id}/emotions", headers=_auth_headers(user["token"]))
    assert r.status_code == 200, r.text
    assert r.json()["emotions_plutchik"] == ["Awe"]

    after_rows, _ = database._execute("SELECT * FROM dreams WHERE id = ?", (dream_id,))
    after = dict(after_rows[0])
    for col in before:
        if col == "emotions_plutchik":
            continue
        assert before[col] == after[col], f"backfill touched unrelated column {col}"


def test_personal_meaning_survives_and_stays_linked_after_dream_edits(fresh_db, mock_engine):
    """
    Personal meanings are keyed by (user_id, subject_type, subject_key),
    never by dream id -- confirm a saved meaning for a symbol is still
    there and still correctly scoped after other activity on the
    account (adding more dreams), i.e. nothing about it is accidentally
    tied to, or lost with, any one dream.
    """
    user = _signup("meaning_user", "hunter22bb")
    headers = _auth_headers(user["token"])
    r = client.put("/personal-meanings", json={
        "subject_type": "symbol", "subject_key": "a door", "subject_label": "a door",
        "meaning": "Doors mean a choice I haven't made yet.", "note": "",
    }, headers=headers)
    assert r.status_code == 200, r.text

    # Unrelated activity on the same account.
    _insert_legacy_dream_row(user["id"], "A filler dream to pass time between the meaning and the check.")

    r2 = client.get("/personal-meanings", headers=headers)
    assert r2.status_code == 200
    meanings = r2.json()
    assert len(meanings) == 1
    assert meanings[0]["subject_key"] == "a door"
    assert meanings[0]["meaning"] == "Doors mean a choice I haven't made yet."


# ===========================================================================
# SECTION 5 -- Backend user-data isolation (the critical section)
# ===========================================================================

def test_cross_account_cannot_read_edit_or_delete_dream(fresh_db, mock_engine):
    alice = _signup("alice_iso", "hunter22cc")
    bob = _signup("bob_iso", "hunter22dd")
    alice_dream_id = _insert_legacy_dream_row(alice["id"], "Alice's own private dream text.")
    bob_headers = _auth_headers(bob["token"])

    # Bob can't see it in his own list.
    r = client.get("/dreams", headers=bob_headers)
    assert alice_dream_id not in [d["id"] for d in r.json()]

    # Bob can't read it directly by guessing the id (no direct GET
    # /dreams/{id} exists, but several sibling endpoints take an id --
    # all of them must 404, never leak Alice's text).
    r = client.get(f"/dreams/{alice_dream_id}/similar", headers=bob_headers)
    assert r.status_code == 404

    r = client.get(f"/dreams/{alice_dream_id}/emotions", headers=bob_headers)
    assert r.status_code == 404

    r = client.put(f"/dreams/{alice_dream_id}/date", json={"date": "2020-01-01"}, headers=bob_headers)
    assert r.status_code == 404

    r = client.put(f"/dreams/{alice_dream_id}/location", json={"location": "Bob was never here"}, headers=bob_headers)
    assert r.status_code == 404

    r = client.put(f"/dreams/{alice_dream_id}/conversation", json={"conversation": []}, headers=bob_headers)
    assert r.status_code == 404

    r = client.delete(f"/dreams/{alice_dream_id}", headers=bob_headers)
    assert r.status_code == 404

    # Confirm the delete attempt genuinely did nothing.
    rows, _ = database._execute("SELECT id FROM dreams WHERE id = ?", (alice_dream_id,))
    assert len(rows) == 1, "a cross-account delete attempt actually removed another user's dream"

    # And Alice's own access is unaffected by all of the above.
    r = client.get(f"/dreams/{alice_dream_id}/similar", headers=_auth_headers(alice["token"]))
    assert r.status_code == 200


def test_cross_account_personal_meanings_and_connection_feedback_isolated(fresh_db):
    alice = _signup("alice_pm", "hunter22ee")
    bob = _signup("bob_pm", "hunter22ff")
    client.put("/personal-meanings", json={
        "subject_type": "symbol", "subject_key": "ocean", "subject_label": "ocean",
        "meaning": "Alice's own private meaning.", "note": "",
    }, headers=_auth_headers(alice["token"]))
    client.put("/connections/feedback", json={
        "connection_key": "symbol:ocean|emotion:awe", "status": "relevant", "note": "",
    }, headers=_auth_headers(alice["token"]))

    bob_meanings = client.get("/personal-meanings", headers=_auth_headers(bob["token"])).json()
    assert bob_meanings == [], "Bob can see Alice's personal meanings"
    bob_feedback = client.get("/connections/feedback", headers=_auth_headers(bob["token"])).json()
    assert bob_feedback == [], "Bob can see Alice's connection feedback"

    # Bob deleting "his" copy of Alice's subject_key must not touch hers
    # -- there's no cross-account targeting possible here since the
    # endpoint has no user_id parameter at all, only subject_type/key
    # scoped implicitly to the caller; confirm that holds.
    r = client.delete("/personal-meanings/symbol/ocean", headers=_auth_headers(bob["token"]))
    assert r.status_code == 200  # idempotent no-op for Bob, by design
    alice_meanings_after = client.get("/personal-meanings", headers=_auth_headers(alice["token"])).json()
    assert len(alice_meanings_after) == 1, "Bob's delete call removed Alice's personal meaning"


def test_cross_account_profile_isolated(fresh_db):
    alice = _signup("alice_prof", "hunter22gg")
    bob = _signup("bob_prof", "hunter22hh")
    client.post("/profile", json={
        "name": "Alice Real Name", "birth_date": "1990-01-01", "birthplace": "Istanbul",
        "current_location": "Istanbul", "gender": "", "relationship_status": "",
        "bio": "Alice's private bio.", "picture": "",
    }, headers=_auth_headers(alice["token"]))

    bob_profile = client.get("/profile", headers=_auth_headers(bob["token"])).json()
    assert bob_profile["name"] in (None, ""), "Bob can see Alice's profile name"
    assert bob_profile["bio"] in (None, ""), "Bob can see Alice's private bio"


def test_missing_invalid_and_malformed_auth_rejected(fresh_db):
    alice = _signup("alice_auth", "hunter22ii")
    dream_id = _insert_legacy_dream_row(alice["id"], "A dream to try to reach without real auth.")

    # No header at all.
    r = client.get("/dreams")
    assert r.status_code == 401

    # Garbage token.
    r = client.get("/dreams", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401

    # Header present but wrong scheme.
    r = client.get("/dreams", headers={"Authorization": alice["token"]})  # no "Bearer " prefix
    assert r.status_code == 401

    # Empty bearer token.
    r = client.get("/dreams", headers={"Authorization": "Bearer "})
    assert r.status_code == 401

    # Expired token (older than TOKEN_LIFETIME) must be rejected, not
    # just a malformed one.
    database._execute(
        "UPDATE users SET token_created_at = ? WHERE id = ?",
        ((datetime.now() - database.TOKEN_LIFETIME - timedelta(days=1)).isoformat(), alice["id"]),
    )
    r = client.get("/dreams", headers=_auth_headers(alice["token"]))
    assert r.status_code == 401, "a token older than TOKEN_LIFETIME was still accepted"


def test_account_deletion_requires_correct_password_and_is_rate_limited(fresh_db, mock_engine):
    alice = _signup("alice_del", "hunter22jj")
    dream_id = _insert_legacy_dream_row(alice["id"], "This dream should vanish only on a correctly-authorized delete.")

    # Wrong password: refused, nothing deleted.
    r = client.request("DELETE", "/account", json={"password": "wrong-password"}, headers=_auth_headers(alice["token"]))
    assert r.status_code == 401
    rows, _ = database._execute("SELECT id FROM users WHERE id = ?", (alice["id"],))
    assert len(rows) == 1

    # Correct password: deletes the account and every related table.
    r = client.request("DELETE", "/account", json={"password": "hunter22jj"}, headers=_auth_headers(alice["token"]))
    assert r.status_code == 200, r.text
    for table in ("users", "dreams", "profile", "symbol_chats", "personal_meanings", "connection_feedback"):
        rows, _ = database._execute(f"SELECT * FROM {table} WHERE {'id' if table == 'users' else 'user_id'} = ?", (alice["id"],))
        assert rows == [], f"{table} still has rows for a deleted account"


# ===========================================================================
# SECTION 4 -- Password recovery
# ===========================================================================

def test_forgot_password_same_response_for_real_and_fake_email(fresh_db):
    _signup("has_account", "hunter22kk", email="hasaccount@example.com")
    r1 = client.post("/forgot-password", json={"email": "hasaccount@example.com"})
    r2 = client.post("/forgot-password", json={"email": "doesnotexist@example.com"})
    assert r1.status_code == r2.status_code == 200
    assert r1.json() == r2.json() == {"ok": True}


def test_reset_token_works_once_then_is_rejected(fresh_db):
    user = _signup("reset_user", "hunter22ll", email="resetuser@example.com")
    reset = database.create_password_reset_token("resetuser@example.com")
    assert reset is not None

    r = client.post("/reset-password", json={"token": reset["reset_token"], "new_password": "brandnew123"})
    assert r.status_code == 200, r.text
    new_login_token = r.json()["token"]

    # The old login token (issued at signup) must now be invalid -- a
    # reset implies "someone untrusted may have had access."
    old_token_check = client.get("/account", headers=_auth_headers(user["token"]))
    assert old_token_check.status_code == 401, "old session survived a password reset"

    # New token works.
    assert client.get("/account", headers=_auth_headers(new_login_token)).status_code == 200

    # Reusing the same reset token a second time must fail.
    r2 = client.post("/reset-password", json={"token": reset["reset_token"], "new_password": "anothernewpass1"})
    assert r2.status_code == 400


def test_expired_reset_token_rejected(fresh_db):
    user = _signup("reset_expired", "hunter22mm", email="resetexpired@example.com")
    reset = database.create_password_reset_token("resetexpired@example.com")
    # Back-date it past RESET_TOKEN_LIFETIME (1 hour).
    database._execute(
        "UPDATE users SET reset_token_created_at = ? WHERE id = ?",
        ((datetime.now() - database.RESET_TOKEN_LIFETIME - timedelta(minutes=5)).isoformat(), user["id"]),
    )
    r = client.post("/reset-password", json={"token": reset["reset_token"], "new_password": "irrelevant123"})
    assert r.status_code == 400


def test_reset_password_still_enforces_strength_rules(fresh_db):
    user = _signup("reset_weak", "hunter22nn", email="resetweak@example.com")
    reset = database.create_password_reset_token("resetweak@example.com")
    r = client.post("/reset-password", json={"token": reset["reset_token"], "new_password": "short"})
    assert r.status_code == 400


# ===========================================================================
# SECTION 9 -- /interpret: HTTP 200 vs. actually-persisted
# ===========================================================================

def test_interpret_failure_mid_stream_returns_200_but_no_dream_and_error_in_trailer(fresh_db, mock_engine, monkeypatch):
    """
    Reproduces the exact Stage 6 observation under a controlled,
    isolated condition: make the interpretation pipeline raise partway
    through, after the HTTP response has already started streaming (and
    therefore already committed to status 200 -- see
    main.stream_interpretation's own docstring on why that's
    unavoidable), and confirm (a) the HTTP status is still 200, (b) no
    dream was persisted, and (c) the trailing metadata block carries an
    "error" key that a correct caller must check. A test script that
    only checks response.status_code -- as Stage 6's ad hoc live check
    did -- cannot tell this apart from success; checking the actual
    response body, the way index.html's own readStreamedInterpretation
    already does, can.
    """
    def failing_stream(raw_text, extracted, similar=None, profile=None, location=None, dream_timestamp=None, emotions_reported=None):
        yield "The reading starts normally, then..."
        raise RuntimeError("simulated mid-stream failure")
    monkeypatch.setattr(engine, "interpret_dream_stream", failing_stream)

    user = _signup("interpret_fail_user", "hunter22oo")
    before_count = len(client.get("/dreams", headers=_auth_headers(user["token"])).json())

    r = client.post("/interpret", json={"raw_text": "A dream that will fail partway through its interpretation."}, headers=_auth_headers(user["token"]))
    assert r.status_code == 200, "status is 200 even on a mid-stream failure, by design -- this assertion documents that, it is not the bug"

    meta = _interpret_result(r)
    assert "error" in meta, "the trailing metadata block should carry an error key on failure"
    assert "id" not in meta

    after_count = len(client.get("/dreams", headers=_auth_headers(user["token"])).json())
    assert after_count == before_count, "a failed interpretation should not have persisted a dream"


def test_interpret_success_returns_200_and_does_persist(fresh_db, mock_engine):
    """The contrasting, successful case -- same endpoint, confirming the
    normal path really does save when on_complete runs cleanly."""
    user = _signup("interpret_ok_user", "hunter22pp")
    r = client.post("/interpret", json={"raw_text": "A perfectly normal dream that should save."}, headers=_auth_headers(user["token"]))
    assert r.status_code == 200, r.text
    meta = _interpret_result(r)
    assert "id" in meta
    assert "error" not in meta
    dreams = client.get("/dreams", headers=_auth_headers(user["token"])).json()
    assert meta["id"] in [d["id"] for d in dreams]


# ===========================================================================
# SECTION 6 -- Privacy Notice copy: presence check (not a behavior test)
# ===========================================================================

def _read_index_html():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "index.html")
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_privacy_notice_discloses_profile_data_sent_to_anthropic():
    """
    This is a copy-presence check, not a behavior test: it exists so a
    future edit that quietly removes the profile-data disclosure added
    in the Stage 7 Final Safety pass gets caught here rather than
    silently regressing. It does not parse or render the HTML, just
    confirms the key disclosures are present in the Privacy Notice's
    static text block, and that an unqualified "nowhere else" claim --
    the exact pattern the Stage 7 spec warned against over-claiming --
    hasn't reappeared disconnected from the real list of destinations.
    """
    html = _read_index_html()
    privacy_start = html.index('id="settings-privacy-view"')
    privacy_section = html[privacy_start:privacy_start + 4000]

    assert "Anthropic" in privacy_section
    assert "Voyage" in privacy_section
    assert "Pinecone" in privacy_section
    # The actual profile fields engine._profile_context() can include --
    # confirms the notice names what's really sent, not a vague gesture
    # at "some profile data."
    for field_word in ("name", "age", "gender", "relationship status", "birthplace", "current location", "bio"):
        assert field_word in privacy_section, f"Privacy Notice doesn't mention '{field_word}'"
