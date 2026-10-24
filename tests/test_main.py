"""
tests/test_main.py -- integration tests for main.py's HTTP endpoints,
using FastAPI's own TestClient (so these go through real routing,
auth, and request/response validation, not just calling functions
directly).

Every Claude and Voyage call is mocked via the mock_engine fixture
below -- this suite costs nothing to run and needs no API keys, and
more importantly, a test suite that calls a real LLM isn't actually
testing the same thing twice in a row (that's what evals/ is for, see
its own README). What's under test here is Loominous's own code: routing,
auth, ownership checks, and response shapes.
"""

import json
import secrets
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import database
import engine
import main

client = TestClient(main.app)


def _interpret_result(response):
    """
    POST /interpret, PUT /dreams/{id}, and GET /patterns all stream their
    response now (see main.stream_interpretation) rather than sending
    one JSON body -- response.json() can't parse that, it would just
    raise. The wire format is the generated text itself, followed by
    main.STREAM_META_SEP and one trailing JSON object carrying whatever
    else that endpoint's non-streamed shape used to send in one piece
    (id/symbols/emotions/etc. for the first two, count for /patterns),
    the exact same split index.html's own readStreamedInterpretation
    does on the frontend. Tests want that trailing object, not the raw
    streamed text, so this is the one place that split happens rather
    than every test reimplementing it -- usable for any of the three.
    """
    text = response.text
    sep_index = text.rindex(main.STREAM_META_SEP)
    return json.loads(text[sep_index + 1:])

FAKE_EXTRACTED = {
    "symbols": ["a door"],
    "emotions": ["curiosity"],
    "emotions_plutchik": ["Trust", "Fear"],
    "people": [],
    "settings": ["a hallway"],
    "themes": ["transition"],
    "symbol_icons": {"a door": "door"},
}


@pytest.fixture
def mock_engine(monkeypatch):
    """Stub out every Claude/Voyage call engine.py makes, so endpoint
    tests exercise Loominous's own routing and database logic without a
    network call or an API key."""
    monkeypatch.setattr(engine, "extract_dream_data", lambda raw_text, emotions_reported=None: dict(FAKE_EXTRACTED))
    monkeypatch.setattr(engine, "embed_text", lambda text, input_type="document": [1.0, 0.0, 0.0])
    # interpret_dream itself is only called by gui.py now (the desktop
    # tool) -- main.py's /interpret and PUT /dreams/{id} both call
    # interpret_dream_stream instead (see engine.py), so that's the one
    # that actually needs stubbing here. Left unstubbed, these tests were
    # silently falling through to the real Claude API on every /interpret
    # call: slow, costs real money, and not what "mock_engine" is for.
    # A one-chunk generator is enough -- stream_interpretation just joins
    # whatever it yields back into one string either way.
    monkeypatch.setattr(engine, "interpret_dream", lambda raw_text, extracted, similar=None, profile=None, location=None, dream_timestamp=None, emotions_reported=None: "A fake reading.")
    def fake_interpret_dream_stream(raw_text, extracted, similar=None, profile=None, location=None, dream_timestamp=None, emotions_reported=None):
        yield "A fake reading."
    monkeypatch.setattr(engine, "interpret_dream_stream", fake_interpret_dream_stream)
    monkeypatch.setattr(engine, "continue_conversation", lambda messages, profile=None, related_dreams=None, search_fn=None, dream_timestamp=None: "A fake reply.")
    monkeypatch.setattr(engine, "analyze_patterns", lambda all_dreams, profile=None, search_fn=None: "**Recurring symbols & themes**\n- a fake pattern")
    # main.py's /patterns route calls analyze_patterns_stream now (see
    # engine.py) -- same "a one-chunk generator is enough" reasoning as
    # interpret_dream_stream above; stream_interpretation just joins
    # whatever it yields either way.
    def fake_analyze_patterns_stream(all_dreams, profile=None, search_fn=None):
        yield "**Recurring symbols & themes**\n- a fake pattern"
    monkeypatch.setattr(engine, "analyze_patterns_stream", fake_analyze_patterns_stream)
    monkeypatch.setattr(engine, "symbol_insight", lambda symbol, occurrences: {"teaser": "A fake teaser.", "meaning": "A fake meaning.", "direction": "A fake question?"})
    monkeypatch.setattr(engine, "symbol_chat_reply", lambda symbol, occurrences, opening_reflection, conversation, message, profile=None: "A fake symbol reply.")
    monkeypatch.setattr(engine, "classify_emotions_plutchik", lambda raw_text, emotions_freetext=None, emotions_reported=None: ["Awe"])


def _signup(username="alice", password="hunter22", email=None):
    # Email is required now (see validate_password_strength / signup()'s
    # own check), so every call site that doesn't care about email
    # specifically gets a sensible default here rather than needing to
    # pass one explicitly everywhere.
    if email is None:
        email = username + "@example.com"
    r = client.post("/signup", json={"username": username, "password": password, "email": email})
    assert r.status_code == 200, r.text
    return r.json()


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# --- Accounts --------------------------------------------------------------

def test_signup_then_login(fresh_db):
    _signup("alice", "hunter22")
    r = client.post("/login", json={"username": "alice", "password": "hunter22"})
    assert r.status_code == 200
    assert r.json()["username"] == "alice"


def test_login_wrong_password_is_401(fresh_db):
    _signup("alice", "hunter22")
    r = client.post("/login", json={"username": "alice", "password": "wrong"})
    assert r.status_code == 401


def test_signup_duplicate_username_is_409(fresh_db):
    _signup("alice", "hunter22")
    r = client.post("/signup", json={"username": "alice", "password": "something-else1", "email": "alice2@example.com"})
    assert r.status_code == 409


def test_signup_duplicate_email_is_409(fresh_db):
    # Same email, different username -- this is the one that matters
    # more than the username check above: without it, two accounts
    # could share one email and /forgot-password's single-row lookup
    # would pick between them arbitrarily.
    _signup("alice", "hunter22", email="shared@example.com")
    r = client.post("/signup", json={"username": "alice2", "password": "something-else1", "email": "shared@example.com"})
    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]


def test_signup_duplicate_email_is_case_insensitive(fresh_db):
    _signup("alice", "hunter22", email="shared@example.com")
    r = client.post("/signup", json={"username": "alice2", "password": "something-else1", "email": "SHARED@example.com"})
    assert r.status_code == 409


def test_endpoint_without_token_is_401(fresh_db):
    r = client.get("/dreams")
    assert r.status_code == 401


def test_endpoint_with_garbage_token_is_401(fresh_db):
    r = client.get("/dreams", headers=_auth_headers("not-a-real-token"))
    assert r.status_code == 401


# --- Logging, editing, deleting a dream -------------------------------------

def test_interpret_creates_a_dream(fresh_db, mock_engine):
    user = _signup()
    r = client.post("/interpret", json={"raw_text": "I was flying."}, headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    body = _interpret_result(r)
    assert body["interpretation"] == "A fake reading."
    assert body["symbols"] == ["a door"]
    assert body["symbol_icons"] == {"a door": "door"}

    listing = client.get("/dreams", headers=_auth_headers(user["token"]))
    assert len(listing.json()) == 1
    assert listing.json()[0]["symbol_icons"] == {"a door": "door"}


def test_interpret_empty_text_is_400(fresh_db, mock_engine):
    user = _signup()
    r = client.post("/interpret", json={"raw_text": "   "}, headers=_auth_headers(user["token"]))
    assert r.status_code == 400


def test_edit_dream_reinterprets_it(fresh_db, mock_engine, monkeypatch):
    user = _signup()
    created = _interpret_result(client.post("/interpret", json={"raw_text": "original"}, headers=_auth_headers(user["token"])))

    new_reading = "A different fake reading."
    def fake_stream(raw_text, extracted, similar=None, profile=None, location=None, dream_timestamp=None, emotions_reported=None):
        yield new_reading
    monkeypatch.setattr(engine, "interpret_dream_stream", fake_stream)
    r = client.put(f"/dreams/{created['id']}", json={"raw_text": "edited"}, headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    assert _interpret_result(r)["interpretation"] == new_reading


def test_edit_nonexistent_dream_is_404(fresh_db, mock_engine):
    user = _signup()
    r = client.put("/dreams/99999", json={"raw_text": "edited"}, headers=_auth_headers(user["token"]))
    assert r.status_code == 404


def test_delete_dream_removes_it(fresh_db, mock_engine):
    user = _signup()
    created = _interpret_result(client.post("/interpret", json={"raw_text": "a dream"}, headers=_auth_headers(user["token"])))

    r = client.delete(f"/dreams/{created['id']}", headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    assert r.json() == {"deleted": True}

    listing = client.get("/dreams", headers=_auth_headers(user["token"]))
    assert listing.json() == []


def test_delete_nonexistent_dream_is_404(fresh_db, mock_engine):
    user = _signup()
    r = client.delete("/dreams/99999", headers=_auth_headers(user["token"]))
    assert r.status_code == 404


# --- Mood tagging + similar dreams ------------------------------------------

def test_interpret_stores_emotions_reported(fresh_db, mock_engine):
    user = _signup()
    body = _interpret_result(client.post(
        "/interpret",
        json={"raw_text": "I was flying.", "emotions_reported": ["Joy", "Fear"]},
        headers=_auth_headers(user["token"]),
    ))
    assert body["emotions_reported"] == ["Joy", "Fear"]

    listing = client.get("/dreams", headers=_auth_headers(user["token"])).json()
    assert listing[0]["emotions_reported"] == ["Joy", "Fear"]


def test_interpret_without_emotions_reported_defaults_empty(fresh_db, mock_engine):
    user = _signup()
    body = _interpret_result(client.post("/interpret", json={"raw_text": "I was flying."}, headers=_auth_headers(user["token"])))
    assert body["emotions_reported"] == []


def test_interpret_returns_emotions_plutchik(fresh_db, mock_engine):
    # emotions_plutchik is the AI's own read, restricted to the same
    # fixed vocabulary emotions_reported is tagged from (see
    # engine.extract_dream_data) -- distinct from the free-text
    # "emotions" field, which keeps whatever words the model reaches for.
    user = _signup()
    body = _interpret_result(client.post(
        "/interpret",
        json={"raw_text": "I was flying.", "emotions_reported": ["Joy"]},
        headers=_auth_headers(user["token"]),
    ))
    assert body["emotions_plutchik"] == ["Trust", "Fear"]
    assert body["emotions"] == ["curiosity"]  # unaffected, still free text

    listing = client.get("/dreams", headers=_auth_headers(user["token"])).json()
    assert listing[0]["emotions_plutchik"] == ["Trust", "Fear"]


def test_extract_dream_data_filters_invalid_plutchik_labels(monkeypatch):
    # The extraction prompt asks for only the fixed eight-word set, but
    # this is the safety net if the model drifts anyway -- same
    # discipline as symbol_icons' own filtering just above it.
    class FakeResponse:
        content = [type("Block", (), {"type": "text", "text": json.dumps({
            "symbols": [], "emotions": [], "emotions_plutchik": ["Trust", "Nostalgic", "fear"],
            "people": [], "settings": [], "themes": [], "symbol_icons": {},
        })})]

    monkeypatch.setattr(engine, "_claude_call", lambda *a, **kw: FakeResponse())
    result = engine.extract_dream_data("a dream")
    # "Nostalgic" isn't in the fixed set and "fear" is the wrong case --
    # both get dropped, leaving only the one exact, valid match.
    assert result["emotions_plutchik"] == ["Trust"]


def test_extract_dream_data_accepts_secondary_plutchik_dyads(monkeypatch):
    # The fixed set isn't just the eight primaries -- Plutchik's own wheel
    # dyads (Awe, Remorse, ...) are valid too (see PLUTCHIK_SECONDARY).
    class FakeResponse:
        content = [type("Block", (), {"type": "text", "text": json.dumps({
            "symbols": [], "emotions": [], "emotions_plutchik": ["Awe", "Remorse"],
            "people": [], "settings": [], "themes": [], "symbol_icons": {},
        })})]

    monkeypatch.setattr(engine, "_claude_call", lambda *a, **kw: FakeResponse())
    result = engine.extract_dream_data("a dream")
    assert result["emotions_plutchik"] == ["Awe", "Remorse"]


def test_interpret_prompt_folds_in_reported_moods_without_quoting_them():
    # emotions_reported should shade the prompt as quiet context, not as
    # literal instructions to echo the words back -- see
    # _build_interpret_prompt's mood_context.
    prompt = engine._build_interpret_prompt(
        "a dream about a locked door", {}, emotions_reported=["Trust", "Fear"],
    )
    assert "Trust, Fear" in prompt
    assert "quietly color" in prompt
    # No emotions_reported at all -- the block should be entirely absent,
    # not just empty-but-present.
    bare_prompt = engine._build_interpret_prompt("a dream about a locked door", {})
    assert "felt sense" not in bare_prompt


def test_similar_dreams_endpoint_finds_other_dreams(fresh_db, mock_engine):
    # mock_engine's embed_text always returns the same constant vector, so
    # any two dreams from it score a perfect 100% match -- this just
    # exercises that the route wires find_similar's real cosine-similarity
    # path together correctly, not the embedding model itself.
    user = _signup()
    first = _interpret_result(client.post("/interpret", json={"raw_text": "Flying over a city."}, headers=_auth_headers(user["token"])))
    client.post("/interpret", json={"raw_text": "Flying over the sea."}, headers=_auth_headers(user["token"]))

    r = client.get(f"/dreams/{first['id']}/similar", headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["match"] == 100
    assert body[0]["snippet"] == "Flying over the sea."
    # The dream itself never shows up in its own "similar" list.
    assert all(d["id"] != first["id"] for d in body)


def test_similar_dreams_excludes_other_users(fresh_db, mock_engine):
    alice = _signup("alice")
    bob = _signup("bob")
    _interpret_result(client.post("/interpret", json={"raw_text": "Alice's dream."}, headers=_auth_headers(alice["token"])))
    bob_dream = _interpret_result(client.post("/interpret", json={"raw_text": "Bob's dream."}, headers=_auth_headers(bob["token"])))

    r = client.get(f"/dreams/{bob_dream['id']}/similar", headers=_auth_headers(bob["token"]))
    assert r.status_code == 200
    assert r.json() == []


def test_similar_dreams_nonexistent_dream_is_404(fresh_db, mock_engine):
    user = _signup()
    r = client.get("/dreams/99999/similar", headers=_auth_headers(user["token"]))
    assert r.status_code == 404


def test_dream_emotions_backfills_when_missing(fresh_db, mock_engine):
    # A dream logged before emotions_plutchik existed: inserted directly
    # (bypassing /interpret, which always populates it now) so it has
    # nothing stored on that field -- the real shape of an old archive
    # entry.
    user = _signup()
    dream_id = database.insert_dream(
        user["id"], "An old dream.",
        {"symbols": [], "emotions": ["calm"], "people": [], "settings": [], "themes": [], "symbol_icons": {}},
        "An old reading.", [1.0, 0.0, 0.0],
    )
    r = client.get(f"/dreams/{dream_id}/emotions", headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    assert r.json()["emotions_plutchik"] == ["Awe"]
    # Persisted -- it shows up in the archive listing from then on with
    # no further classification call needed.
    listing = client.get("/dreams", headers=_auth_headers(user["token"])).json()
    assert listing[0]["emotions_plutchik"] == ["Awe"]


def test_dream_emotions_skips_classification_when_already_present(fresh_db, mock_engine, monkeypatch):
    # A dream /interpret already ran on has emotions_plutchik from the
    # start (FAKE_EXTRACTED) -- this should return it directly rather
    # than spending another Claude call to re-derive the same thing.
    user = _signup()
    created = _interpret_result(client.post("/interpret", json={"raw_text": "A dream."}, headers=_auth_headers(user["token"])))
    calls = []
    monkeypatch.setattr(engine, "classify_emotions_plutchik", lambda raw_text, emotions_freetext=None, emotions_reported=None: calls.append(1) or ["Awe"])

    r = client.get(f"/dreams/{created['id']}/emotions", headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    assert r.json()["emotions_plutchik"] == ["Trust", "Fear"]
    assert calls == []


def test_dream_emotions_nonexistent_dream_is_404(fresh_db, mock_engine):
    user = _signup()
    r = client.get("/dreams/99999/emotions", headers=_auth_headers(user["token"]))
    assert r.status_code == 404


# --- Ownership isolation, end to end through the API ------------------------

def test_cannot_read_another_users_dream_via_archive(fresh_db, mock_engine):
    alice = _signup("alice")
    bob = _signup("bob")
    client.post("/interpret", json={"raw_text": "alice's secret"}, headers=_auth_headers(alice["token"]))

    bobs_view = client.get("/dreams", headers=_auth_headers(bob["token"]))
    assert bobs_view.json() == []


def test_cannot_edit_another_users_dream_via_api(fresh_db, mock_engine):
    alice = _signup("alice")
    bob = _signup("bob")
    created = _interpret_result(client.post("/interpret", json={"raw_text": "alice's dream"}, headers=_auth_headers(alice["token"])))

    r = client.put(f"/dreams/{created['id']}", json={"raw_text": "bob tries to overwrite this"}, headers=_auth_headers(bob["token"]))
    assert r.status_code == 404  # looks the same as "doesn't exist" from bob's side -- no leak either way


def test_cannot_delete_another_users_dream_via_api(fresh_db, mock_engine):
    alice = _signup("alice")
    bob = _signup("bob")
    created = _interpret_result(client.post("/interpret", json={"raw_text": "alice's dream"}, headers=_auth_headers(alice["token"])))

    r = client.delete(f"/dreams/{created['id']}", headers=_auth_headers(bob["token"]))
    assert r.status_code == 404

    # Still there for its real owner.
    still_there = client.get("/dreams", headers=_auth_headers(alice["token"]))
    assert len(still_there.json()) == 1


# --- Patterns and health -----------------------------------------------------

def test_patterns_reports_dream_count(fresh_db, mock_engine):
    user = _signup()
    client.post("/interpret", json={"raw_text": "one dream"}, headers=_auth_headers(user["token"]))
    r = client.get("/patterns", headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    assert _interpret_result(r)["count"] == 1


def test_patterns_includes_an_emotion_sequence_for_the_drift_chart(fresh_db, mock_engine):
    # Every dream mock_engine creates is tagged emotions_plutchik =
    # ["Trust", "Fear"] (see FAKE_EXTRACTED), so each entry's dominant
    # emotion -- the first one -- should be "Trust", oldest to newest,
    # one per logged dream, each carrying its own date.
    user = _signup()
    client.post("/interpret", json={"raw_text": "first"}, headers=_auth_headers(user["token"]))
    client.post("/interpret", json={"raw_text": "second"}, headers=_auth_headers(user["token"]))
    r = client.get("/patterns", headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    seq = _interpret_result(r)["emotion_sequence"]
    assert len(seq) == 2
    assert all(entry["emotion"] == "Trust" for entry in seq)
    assert all("date" in entry for entry in seq)


# --- Per-symbol insight: a grounded reflection, not a dictionary lookup -----

def test_symbol_insight_for_a_symbol_in_the_archive(fresh_db, mock_engine):
    user = _signup()
    # mock_engine's extract_dream_data always returns FAKE_EXTRACTED, whose
    # symbols include "a door" -- matching is case-insensitive.
    client.post("/interpret", json={"raw_text": "walked through a door"}, headers=_auth_headers(user["token"]))

    r = client.post("/symbols/insight", json={"symbol": "A Door"}, headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    body = r.json()
    assert body["teaser"] == "A fake teaser."
    assert body["meaning"] == "A fake meaning."
    assert body["direction"] == "A fake question?"


def test_symbol_insight_matches_a_theme_too(fresh_db, mock_engine):
    user = _signup()
    client.post("/interpret", json={"raw_text": "a dream about change"}, headers=_auth_headers(user["token"]))
    r = client.post("/symbols/insight", json={"symbol": "transition"}, headers=_auth_headers(user["token"]))
    assert r.status_code == 200


def test_symbol_insight_404s_for_a_symbol_not_in_the_archive(fresh_db, mock_engine):
    user = _signup()
    client.post("/interpret", json={"raw_text": "a dream"}, headers=_auth_headers(user["token"]))
    r = client.post("/symbols/insight", json={"symbol": "a spaceship"}, headers=_auth_headers(user["token"]))
    assert r.status_code == 404


def test_symbol_insight_needs_auth(fresh_db, mock_engine):
    r = client.post("/symbols/insight", json={"symbol": "a door"})
    assert r.status_code == 401


def test_symbol_insight_only_sees_your_own_archive(fresh_db, mock_engine):
    alice = _signup("alice")
    bob = _signup("bob")
    client.post("/interpret", json={"raw_text": "alice's dream"}, headers=_auth_headers(alice["token"]))
    r = client.post("/symbols/insight", json={"symbol": "a door"}, headers=_auth_headers(bob["token"]))
    assert r.status_code == 404


# --- Each symbol's own chat thread ------------------------------------------

def test_symbol_chat_starts_empty(fresh_db, mock_engine):
    user = _signup()
    client.post("/interpret", json={"raw_text": "a dream"}, headers=_auth_headers(user["token"]))
    r = client.get("/symbols/chat", params={"symbol": "a door"}, headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    assert r.json()["conversation"] == []


def test_symbol_chat_send_and_persist(fresh_db, mock_engine):
    user = _signup()
    client.post("/interpret", json={"raw_text": "a dream"}, headers=_auth_headers(user["token"]))

    r = client.post(
        "/symbols/chat",
        json={"symbol": "a door", "message": "what does it mean"},
        headers=_auth_headers(user["token"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "A fake symbol reply."
    assert body["conversation"] == [
        {"role": "user", "content": "what does it mean"},
        {"role": "assistant", "content": "A fake symbol reply."},
    ]

    # The thread persists -- a fresh GET sees what the POST just saved.
    r2 = client.get("/symbols/chat", params={"symbol": "a door"}, headers=_auth_headers(user["token"]))
    assert r2.json()["conversation"] == body["conversation"]


def test_symbol_chat_404s_for_a_symbol_not_in_the_archive(fresh_db, mock_engine):
    user = _signup()
    client.post("/interpret", json={"raw_text": "a dream"}, headers=_auth_headers(user["token"]))
    r = client.post(
        "/symbols/chat", json={"symbol": "a spaceship", "message": "hi"},
        headers=_auth_headers(user["token"]),
    )
    assert r.status_code == 404


def test_symbol_chat_rejects_an_empty_message(fresh_db, mock_engine):
    user = _signup()
    client.post("/interpret", json={"raw_text": "a dream"}, headers=_auth_headers(user["token"]))
    r = client.post(
        "/symbols/chat", json={"symbol": "a door", "message": "   "},
        headers=_auth_headers(user["token"]),
    )
    assert r.status_code == 400


def test_symbol_chat_needs_auth(fresh_db, mock_engine):
    r = client.get("/symbols/chat", params={"symbol": "a door"})
    assert r.status_code == 401
    r = client.post("/symbols/chat", json={"symbol": "a door", "message": "hi"})
    assert r.status_code == 401


def test_symbol_chat_is_one_thread_regardless_of_which_dream_you_open_it_from(fresh_db, mock_engine):
    # "a door" can turn up in more than one dream -- the conversation
    # about it should be the SAME thread either way, not reset per dream.
    user = _signup()
    client.post("/interpret", json={"raw_text": "first dream"}, headers=_auth_headers(user["token"]))
    client.post("/interpret", json={"raw_text": "second dream"}, headers=_auth_headers(user["token"]))

    client.post(
        "/symbols/chat", json={"symbol": "a door", "message": "first message"},
        headers=_auth_headers(user["token"]),
    )
    r = client.get("/symbols/chat", params={"symbol": "A Door"}, headers=_auth_headers(user["token"]))
    assert len(r.json()["conversation"]) == 2


def test_symbol_chat_only_sees_your_own_thread(fresh_db, mock_engine):
    alice = _signup("alice")
    bob = _signup("bob")
    client.post("/interpret", json={"raw_text": "alice's dream"}, headers=_auth_headers(alice["token"]))
    client.post("/interpret", json={"raw_text": "bob's dream"}, headers=_auth_headers(bob["token"]))

    client.post(
        "/symbols/chat", json={"symbol": "a door", "message": "alice's message"},
        headers=_auth_headers(alice["token"]),
    )
    r = client.get("/symbols/chat", params={"symbol": "a door"}, headers=_auth_headers(bob["token"]))
    assert r.json()["conversation"] == []


def test_symbol_chat_skips_a_redundant_symbol_insight_call_when_given_one(fresh_db, mock_engine, monkeypatch):
    # The frontend already has the opening reflection on screen; passing
    # it along should mean the server never has to regenerate it.
    user = _signup()
    client.post("/interpret", json={"raw_text": "a dream"}, headers=_auth_headers(user["token"]))

    called = {"count": 0}

    def fake_symbol_insight(symbol, occurrences):
        called["count"] += 1
        return {"teaser": "t", "meaning": "m", "direction": "d"}

    monkeypatch.setattr(engine, "symbol_insight", fake_symbol_insight)
    r = client.post(
        "/symbols/chat",
        json={"symbol": "a door", "message": "hi", "meaning": "already shown meaning", "direction": "already shown question"},
        headers=_auth_headers(user["token"]),
    )
    assert r.status_code == 200
    assert called["count"] == 0


# --- Agentic retrieval: search_fn actually gets wired through ---------------
# mock_engine stubs analyze_patterns/continue_conversation entirely, so it
# can't tell us whether main.py bothered to build and pass a real
# search_fn versus just leaving it None. These two tests replace the stub
# with something that inspects what it was handed instead.

def test_patterns_passes_a_working_search_fn(fresh_db, mock_engine, monkeypatch):
    user = _signup()
    client.post("/interpret", json={"raw_text": "a dream"}, headers=_auth_headers(user["token"]))

    captured = {}

    def fake_analyze_stream(all_dreams, profile=None, search_fn=None):
        captured["search_fn"] = search_fn
        yield "ok"

    monkeypatch.setattr(engine, "analyze_patterns_stream", fake_analyze_stream)
    r = client.get("/patterns", headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    assert callable(captured["search_fn"])
    # And it's genuinely wired to this user's own retrieval path, not a
    # no-op stand-in -- calling it exercises embed_text + find_similar()
    # for real (mock_engine's embed_text returns a fixed vector, so the
    # one dream just created, embedded identically, comes back as its
    # own best match) rather than raising or silently doing nothing.
    results = captured["search_fn"]("anything", 3)
    assert len(results) == 1
    assert results[0]["raw_text"] == "a dream"


def test_continue_passes_a_working_search_fn(fresh_db, mock_engine, monkeypatch):
    user = _signup()
    created = _interpret_result(client.post(
        "/interpret", json={"raw_text": "a dream"}, headers=_auth_headers(user["token"]),
    ))

    captured = {}

    def fake_continue(messages, profile=None, related_dreams=None, search_fn=None, dream_timestamp=None):
        captured["search_fn"] = search_fn
        return "a reply"

    monkeypatch.setattr(engine, "continue_conversation", fake_continue)
    r = client.post(
        f"/dreams/{created['id']}/continue", json={"message": "more detail"},
        headers=_auth_headers(user["token"]),
    )
    assert r.status_code == 200
    assert callable(captured["search_fn"])


def test_health_reports_database_ok(fresh_db):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["database"] == "ok"
    # No PINECONE_API_KEY in the test environment (see conftest.py) --
    # "not_configured" is the correct, honest answer here, not an error.
    assert body["pinecone"] == "not_configured"


def test_real_account_can_edit_and_delete_dreams(fresh_db, mock_engine):
    alice = _signup("alice")
    client.post("/interpret", json={"raw_text": "a real dream"}, headers=_auth_headers(alice["token"]))
    dream_id = client.get("/dreams", headers=_auth_headers(alice["token"])).json()[0]["id"]

    assert client.put(
        f"/dreams/{dream_id}/location", json={"location": "Tokyo"}, headers=_auth_headers(alice["token"])
    ).status_code == 200
    assert client.delete(f"/dreams/{dream_id}", headers=_auth_headers(alice["token"])).status_code == 200


def test_account_is_not_capped_on_dream_count(fresh_db, mock_engine):
    alice = _signup("alice")
    for i in range(5):
        r = client.post("/interpret", json={"raw_text": "dream " + str(i)}, headers=_auth_headers(alice["token"]))
        assert r.status_code == 200

    listing = client.get("/dreams", headers=_auth_headers(alice["token"])).json()
    assert len(listing) == 5


# --- Password strength ------------------------------------------------

def test_signup_rejects_short_password(fresh_db):
    r = client.post("/signup", json={"username": "alice", "password": "ab1", "email": "alice@example.com"})
    assert r.status_code == 400
    assert "8 characters" in r.json()["detail"]


def test_signup_rejects_all_letters_password(fresh_db):
    r = client.post("/signup", json={"username": "alice", "password": "nodigitshere", "email": "alice@example.com"})
    assert r.status_code == 400
    assert "number" in r.json()["detail"]


def test_signup_rejects_all_numbers_password(fresh_db):
    r = client.post("/signup", json={"username": "alice", "password": "8675309123", "email": "alice@example.com"})
    assert r.status_code == 400
    assert "letter" in r.json()["detail"]


def test_signup_rejects_common_password(fresh_db):
    r = client.post("/signup", json={"username": "alice", "password": "Password123", "email": "alice@example.com"})
    assert r.status_code == 400
    assert "common" in r.json()["detail"]


def test_signup_accepts_a_reasonably_strong_password(fresh_db):
    r = client.post("/signup", json={"username": "alice", "password": "correcthorse9", "email": "alice@example.com"})
    assert r.status_code == 200


def test_reset_password_enforces_the_same_rules(fresh_db, monkeypatch):
    monkeypatch.setattr(main, "FRONTEND_URL", "https://example.com")
    captured = {}
    monkeypatch.setattr(
        main.emailer, "send_password_reset_email",
        lambda to_email, reset_url: captured.update(reset_url=reset_url) or True,
    )
    client.post("/signup", json={"username": "alice", "password": "hunter2222", "email": "alice@example.com"})
    client.post("/forgot-password", json={"email": "alice@example.com"})
    token = captured["reset_url"].split("reset=")[1]

    r = client.post("/reset-password", json={"token": token, "new_password": "short1"})
    assert r.status_code == 400


# --- Forgot / reset password -------------------------------------------

def test_signup_rejects_bad_looking_email(fresh_db):
    r = client.post("/signup", json={"username": "alice", "password": "hunter22", "email": "not-an-email"})
    assert r.status_code == 400


def test_signup_without_email_is_400(fresh_db):
    # Email became required once password reset depended on it --
    # without one, an account could never be recovered.
    r = client.post("/signup", json={"username": "alice", "password": "hunter22"})
    assert r.status_code == 400
    assert "mail" in r.json()["detail"]


def test_forgot_password_sends_email_for_known_address(fresh_db, monkeypatch):
    monkeypatch.setattr(main, "FRONTEND_URL", "https://example.com")
    captured = {}
    monkeypatch.setattr(
        main.emailer, "send_password_reset_email",
        lambda to_email, reset_url: captured.update(to_email=to_email, reset_url=reset_url) or True,
    )
    client.post("/signup", json={"username": "alice", "password": "hunter22", "email": "alice@example.com"})

    r = client.post("/forgot-password", json={"email": "alice@example.com"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert captured["to_email"] == "alice@example.com"
    assert "reset=" in captured["reset_url"]


def test_forgot_password_same_response_for_unknown_email(fresh_db, monkeypatch):
    # No enumeration: an email nobody signed up with gets the exact same
    # {"ok": true} response, and never triggers a send.
    monkeypatch.setattr(main, "FRONTEND_URL", "https://example.com")
    sent = {"called": False}
    monkeypatch.setattr(
        main.emailer, "send_password_reset_email",
        lambda *a, **k: sent.update(called=True) or True,
    )
    r = client.post("/forgot-password", json={"email": "nobody@example.com"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert sent["called"] is False


def test_forgot_password_without_frontend_url_does_not_send(fresh_db, monkeypatch):
    # FRONTEND_URL unset (the default in this test env) -- a reset token
    # can still be created, but there's no working link to put in an
    # email, so nothing should be sent.
    sent = {"called": False}
    monkeypatch.setattr(
        main.emailer, "send_password_reset_email",
        lambda *a, **k: sent.update(called=True) or True,
    )
    client.post("/signup", json={"username": "alice", "password": "hunter22", "email": "alice@example.com"})
    r = client.post("/forgot-password", json={"email": "alice@example.com"})
    assert r.status_code == 200
    assert sent["called"] is False


def test_reset_password_with_valid_token_logs_in_and_rotates_password(fresh_db, monkeypatch):
    monkeypatch.setattr(main, "FRONTEND_URL", "https://example.com")
    captured = {}
    monkeypatch.setattr(
        main.emailer, "send_password_reset_email",
        lambda to_email, reset_url: captured.update(reset_url=reset_url) or True,
    )
    client.post("/signup", json={"username": "alice", "password": "hunter22", "email": "alice@example.com"})
    client.post("/forgot-password", json={"email": "alice@example.com"})
    token = captured["reset_url"].split("reset=")[1]

    r = client.post("/reset-password", json={"token": token, "new_password": "brandnewpass1"})
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "alice"
    assert "token" in body

    assert client.post("/login", json={"username": "alice", "password": "hunter22"}).status_code == 401
    assert client.post("/login", json={"username": "alice", "password": "brandnewpass1"}).status_code == 200


def test_reset_password_token_is_single_use(fresh_db, monkeypatch):
    monkeypatch.setattr(main, "FRONTEND_URL", "https://example.com")
    captured = {}
    monkeypatch.setattr(
        main.emailer, "send_password_reset_email",
        lambda to_email, reset_url: captured.update(reset_url=reset_url) or True,
    )
    client.post("/signup", json={"username": "alice", "password": "hunter22", "email": "alice@example.com"})
    client.post("/forgot-password", json={"email": "alice@example.com"})
    token = captured["reset_url"].split("reset=")[1]

    first = client.post("/reset-password", json={"token": token, "new_password": "brandnewpass1"})
    assert first.status_code == 200
    # A perfectly strong password, so this 400 can only be the
    # already-spent token, not a strength rejection.
    second = client.post("/reset-password", json={"token": token, "new_password": "Another-Strong-Pass9"})
    assert second.status_code == 400


def test_reset_password_bad_token_is_400(fresh_db):
    r = client.post("/reset-password", json={"token": "not-a-real-token", "new_password": "whatever123"})
    assert r.status_code == 400


# --- Login by username or email ----------------------------------------

def test_login_with_email_instead_of_username(fresh_db):
    _signup("alice", "hunter22", email="alice@example.com")
    r = client.post("/login", json={"username": "alice@example.com", "password": "hunter22"})
    assert r.status_code == 200
    assert r.json()["username"] == "alice"


def test_login_with_email_is_case_insensitive(fresh_db):
    _signup("alice", "hunter22", email="alice@example.com")
    r = client.post("/login", json={"username": "ALICE@EXAMPLE.COM", "password": "hunter22"})
    assert r.status_code == 200


def test_login_with_someone_elses_email_does_not_leak_into_wrong_account(fresh_db):
    _signup("alice", "hunter22", email="alice@example.com")
    _signup("bob", "hunter33", email="bob@example.com")
    # Right email, wrong password -- must not somehow succeed as a
    # different account or leak which account it matched.
    r = client.post("/login", json={"username": "alice@example.com", "password": "hunter33"})
    assert r.status_code == 401


# --- Email verification (legacy accounts only) ---------------------------
# Verification-via-emailed-link is no longer part of signing up: email is
# already required and taken at face value, so a brand-new account comes
# back already verified (see database.create_user). The nudge
# banner/resend/verify-email machinery below still exists and still
# works -- it's only ever reached by an account that was already sitting
# unverified from *before* this stopped being the rule for new ones.
# _make_legacy_unverified_account simulates exactly that shape directly
# at the database layer, since a fresh signup can't produce it anymore.

def _make_legacy_unverified_account(username, email):
    user = _signup(username, "hunter22", email=email)
    verify_token = secrets.token_hex(32)
    database._execute(
        "UPDATE users SET email_verified = 0, verify_token = ?, verify_token_created_at = ? WHERE id = ?",
        (verify_token, datetime.now().isoformat(), user["id"])
    )
    return user, verify_token


def test_new_signup_starts_already_verified(fresh_db):
    user = _signup("alice", "hunter22", email="alice@example.com")
    r = client.get("/account", headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert body["email_verified"] is True


def test_signup_sends_no_verification_email(fresh_db, monkeypatch):
    monkeypatch.setattr(main, "FRONTEND_URL", "https://example.com")
    sent = {"called": False}
    monkeypatch.setattr(
        main.emailer, "send_verification_email",
        lambda *a, **k: sent.update(called=True) or True,
    )
    _signup("alice", "hunter22", email="alice@example.com")
    assert sent["called"] is False


def test_legacy_unverified_account_can_still_log_dreams(fresh_db, mock_engine):
    # "Nudge, don't block" still applies to whatever legacy accounts
    # this matters for -- an unconfirmed email must never stop someone
    # from actually using the app.
    user, _ = _make_legacy_unverified_account("alice", "alice@example.com")
    r = client.post("/interpret", json={"raw_text": "a dream"}, headers=_auth_headers(user["token"]))
    assert r.status_code == 200


def test_legacy_account_can_verify_via_token(fresh_db):
    user, verify_token = _make_legacy_unverified_account("alice", "alice@example.com")

    r = client.post("/verify-email", json={"token": verify_token})
    assert r.status_code == 200
    assert r.json() == {"verified": True}

    account = client.get("/account", headers=_auth_headers(user["token"])).json()
    assert account["email_verified"] is True


def test_verify_email_bad_token_is_400(fresh_db):
    r = client.post("/verify-email", json={"token": "not-a-real-token"})
    assert r.status_code == 400


def test_legacy_account_can_resend_verification(fresh_db, monkeypatch):
    monkeypatch.setattr(main, "FRONTEND_URL", "https://example.com")
    captured = {}
    monkeypatch.setattr(
        main.emailer, "send_verification_email",
        lambda to_email, verify_url: captured.update(to_email=to_email, verify_url=verify_url) or True,
    )
    user, _ = _make_legacy_unverified_account("alice", "alice@example.com")

    r = client.post("/resend-verification", headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    assert r.json() == {"sent": True}
    assert captured["to_email"] == "alice@example.com"


def test_resend_verification_needs_auth(fresh_db):
    r = client.post("/resend-verification")
    assert r.status_code == 401


def test_resend_verification_noop_for_an_already_verified_account(fresh_db):
    # A normal, freshly-signed-up account -- already verified by
    # default now -- has nothing to resend.
    user = _signup("alice", "hunter22", email="alice@example.com")
    r = client.post("/resend-verification", headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    assert r.json() == {"sent": False}


# --- Adding an email to an account that has none (legacy accounts) -------
# Simulates an account from before email was required at signup, since a
# fresh signup can't produce that shape anymore either (same reasoning as
# _make_legacy_unverified_account above, just with email itself blank
# rather than merely unverified).

def _make_legacy_account_with_no_email(username):
    user = _signup(username, "hunter22", email=f"{username}@example.com")
    database._execute(
        "UPDATE users SET email = '', email_verified = 0 WHERE id = ?", (user["id"],)
    )
    return user


def test_account_with_no_email_gets_the_add_email_nudge(fresh_db):
    user = _make_legacy_account_with_no_email("alice")
    r = client.get("/account", headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    assert r.json()["email"] == ""


def test_set_account_email_saves_it_and_sends_a_verification_link(fresh_db, monkeypatch):
    monkeypatch.setattr(main, "FRONTEND_URL", "https://example.com")
    captured = {}
    monkeypatch.setattr(
        main.emailer, "send_verification_email",
        lambda to_email, verify_url: captured.update(to_email=to_email, verify_url=verify_url) or True,
    )
    user = _make_legacy_account_with_no_email("alice")

    r = client.post("/account/email", json={"email": "alice@example.com"}, headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    assert r.json() == {"sent": True}
    assert captured["to_email"] == "alice@example.com"

    account = client.get("/account", headers=_auth_headers(user["token"])).json()
    assert account["email"] == "alice@example.com"
    # Freshly added, so it still needs confirming -- not taken on faith
    # just because someone with a valid session typed it in.
    assert account["email_verified"] is False


def test_set_account_email_needs_auth(fresh_db):
    r = client.post("/account/email", json={"email": "alice@example.com"})
    assert r.status_code == 401


def test_set_account_email_rejects_a_bad_address(fresh_db):
    user = _make_legacy_account_with_no_email("alice")
    r = client.post("/account/email", json={"email": "not-an-email"}, headers=_auth_headers(user["token"]))
    assert r.status_code == 400


def test_set_account_email_rejects_an_email_already_on_another_account(fresh_db, monkeypatch):
    monkeypatch.setattr(main, "FRONTEND_URL", "https://example.com")
    monkeypatch.setattr(main.emailer, "send_verification_email", lambda *a, **k: True)
    _signup("bob", "hunter22", email="bob@example.com")
    user = _make_legacy_account_with_no_email("alice")

    r = client.post("/account/email", json={"email": "bob@example.com"}, headers=_auth_headers(user["token"]))
    assert r.status_code == 409


def test_set_account_email_is_rate_limited_per_account(fresh_db, monkeypatch):
    # The limit is 5/hour, keyed by account rather than IP -- same
    # reasoning as /resend-verification's limit.
    monkeypatch.setattr(main, "FRONTEND_URL", "https://example.com")
    monkeypatch.setattr(main.emailer, "send_verification_email", lambda *a, **k: True)
    user = _make_legacy_account_with_no_email("alice")
    headers = _auth_headers(user["token"])
    for _ in range(5):
        r = client.post("/account/email", json={"email": "alice@example.com"}, headers=headers)
        assert r.status_code == 200
    r = client.post("/account/email", json={"email": "alice@example.com"}, headers=headers)
    assert r.status_code == 429


def test_logout_invalidates_the_token(fresh_db):
    # Before POST /logout existed, "logging out" only ever cleared the
    # browser's own local storage -- the token itself stayed valid
    # server-side until it naturally expired. This is the thing that
    # closes that gap: the exact same token must stop working the
    # moment it's used to log out.
    user = _signup()
    headers = _auth_headers(user["token"])
    assert client.get("/account", headers=headers).status_code == 200

    r = client.post("/logout", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"logged_out": True}

    assert client.get("/account", headers=headers).status_code == 401


def test_logout_needs_auth(fresh_db):
    r = client.post("/logout")
    assert r.status_code == 401


def test_interpret_is_rate_limited_per_account(fresh_db, mock_engine):
    # The budget is 40/hour, keyed by account -- shared with PUT
    # /dreams/{id}'s own re-interpret path, since both call the same
    # underlying Claude pipeline (see require_ai_budget in main.py). This
    # exists to bound per-account API spend -- a leaked token, or a stuck
    # client-side retry loop, shouldn't be able to run that up without
    # limit.
    user = _signup()
    headers = _auth_headers(user["token"])
    for i in range(40):
        r = client.post("/interpret", json={"raw_text": "dream " + str(i)}, headers=headers)
        assert r.status_code == 200, r.text
    r = client.post("/interpret", json={"raw_text": "one too many"}, headers=headers)
    assert r.status_code == 429


def test_health_needs_no_auth(fresh_db):
    # Deliberately no Authorization header -- a monitoring tool can't
    # supply one, so this must never 401.
    r = client.get("/health")
    assert r.status_code == 200


# --- Rate limiting -------------------------------------------------------

def test_signup_is_rate_limited_per_ip(fresh_db):
    # The limit is 10/hour; the 11th signup attempt from the same caller
    # within the window should be rejected before it ever reaches
    # database.create_user -- distinct usernames each time so a 409
    # (username taken) can't be mistaken for the 429 under test.
    for i in range(10):
        r = client.post("/signup", json={
            "username": f"ratelimited{i}", "password": "hunter22",
            "email": f"ratelimited{i}@example.com",
        })
        assert r.status_code == 200, r.text
    r = client.post("/signup", json={
        "username": "oneTooMany", "password": "hunter22",
        "email": "oneTooMany@example.com",
    })
    assert r.status_code == 429


def test_login_is_rate_limited_per_ip(fresh_db):
    # The limit is 15/15min. Wrong password every time, so this also
    # doubles as proof the limiter kicks in before a brute-force run
    # could get anywhere.
    client.post("/signup", json={"username": "alice", "password": "hunter22", "email": "alice@example.com"})
    for _ in range(15):
        r = client.post("/login", json={"username": "alice", "password": "wrong"})
        assert r.status_code == 401
    r = client.post("/login", json={"username": "alice", "password": "wrong"})
    assert r.status_code == 429


def test_forgot_password_is_rate_limited_and_still_returns_ok(fresh_db, monkeypatch):
    # The limit is 5/hour. Once hit, forgot-password must keep returning
    # the same {"ok": true} it always does (see
    # test_forgot_password_same_response_for_unknown_email) -- a 429 here
    # instead would itself be a tell that the limit, not the email
    # lookup, is what's blocking the request.
    sent = {"count": 0}
    monkeypatch.setattr(
        main.emailer, "send_password_reset_email",
        lambda *a, **k: sent.update(count=sent["count"] + 1) or True,
    )
    for _ in range(5):
        r = client.post("/forgot-password", json={"email": "nobody@example.com"})
        assert r.status_code == 200
    r = client.post("/forgot-password", json={"email": "nobody@example.com"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_resend_verification_is_rate_limited_per_account(fresh_db, monkeypatch):
    # The limit is 3/hour, keyed by account rather than IP.
    monkeypatch.setattr(main, "FRONTEND_URL", "https://example.com")
    monkeypatch.setattr(main.emailer, "send_verification_email", lambda *a, **k: True)
    user, _ = _make_legacy_unverified_account("alice", "alice@example.com")
    headers = _auth_headers(user["token"])
    for _ in range(3):
        r = client.post("/resend-verification", headers=headers)
        assert r.status_code == 200
        assert r.json()["sent"] is True
    r = client.post("/resend-verification", headers=headers)
    assert r.status_code == 200
    assert r.json()["sent"] is False


# --- Profile ---------------------------------------------------------------

def test_profile_round_trip_with_all_fields(fresh_db):
    signup = _signup()
    headers = _auth_headers(signup["token"])
    payload = {
        "name": "Alice",
        "birth_date": "1994-03-12",
        "birthplace": "Istanbul",
        "current_location": "Austin",
        "gender": "Woman",
        "relationship_status": "Married",
        "bio": "Just moved to a new city.",
        "picture": "data:image/jpeg;base64,/9j/thisIsNotRealImageDataJustAPlaceholder",
    }
    r = client.post("/profile", json=payload, headers=headers)
    assert r.status_code == 200
    assert r.json() == payload

    r = client.get("/profile", headers=headers)
    assert r.status_code == 200
    assert r.json() == payload


def test_profile_rejects_an_oversized_picture(fresh_db):
    signup = _signup()
    headers = _auth_headers(signup["token"])
    huge = "data:image/jpeg;base64," + ("a" * 500_000)
    r = client.post("/profile", json={"picture": huge}, headers=headers)
    assert r.status_code == 400


def test_profile_needs_auth(fresh_db):
    r = client.get("/profile")
    assert r.status_code == 401
    r = client.post("/profile", json={"name": "Alice"})
    assert r.status_code == 401


# --- Account deletion ------------------------------------------------------

def test_delete_account_removes_everything(fresh_db, mock_engine):
    signup = _signup()
    headers = _auth_headers(signup["token"])
    client.post("/interpret", json={"raw_text": "A dream about doors."}, headers=headers)
    client.post("/profile", json={"name": "Alice"}, headers=headers)

    r = client.request("DELETE", "/account", json={"password": "hunter22"}, headers=headers)
    assert r.status_code == 200
    assert r.json() == {"deleted": True}

    # The same token no longer authenticates anything.
    r = client.get("/account", headers=headers)
    assert r.status_code == 401

    # The username is free again -- a fresh signup with it should work,
    # proof the user row itself (not just its token) is really gone.
    r = client.post("/signup", json={
        "username": signup["username"], "password": "hunter22",
        "email": "alice2@example.com",
    })
    assert r.status_code == 200


def test_delete_account_needs_auth(fresh_db):
    # A body is supplied so this fails on the auth check specifically,
    # not on a 422 for a missing password field.
    r = client.request("DELETE", "/account", json={"password": "hunter22"})
    assert r.status_code == 401


def test_delete_account_wrong_password_is_rejected(fresh_db):
    signup = _signup()
    headers = _auth_headers(signup["token"])

    r = client.request("DELETE", "/account", json={"password": "wrongpassword1"}, headers=headers)
    assert r.status_code == 401

    # Nothing was actually deleted -- the same token still works.
    r = client.get("/account", headers=headers)
    assert r.status_code == 200


def test_delete_account_only_removes_the_calling_account(fresh_db, mock_engine):
    alice = _signup(username="alice")
    bob = _signup(username="bob")
    client.post("/interpret", json={"raw_text": "Alice's dream."}, headers=_auth_headers(alice["token"]))
    client.post("/interpret", json={"raw_text": "Bob's dream."}, headers=_auth_headers(bob["token"]))

    r = client.request("DELETE", "/account", json={"password": "hunter22"}, headers=_auth_headers(alice["token"]))
    assert r.status_code == 200

    # Bob's account and dream are untouched.
    r = client.get("/dreams", headers=_auth_headers(bob["token"]))
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_delete_account_is_rate_limited_per_account(fresh_db):
    # The limit is 5/15min, keyed by account -- wrong password every
    # time, same shape as the login rate-limit test.
    signup = _signup()
    headers = _auth_headers(signup["token"])
    for _ in range(5):
        r = client.request("DELETE", "/account", json={"password": "wrongpassword1"}, headers=headers)
        assert r.status_code == 401
    r = client.request("DELETE", "/account", json={"password": "wrongpassword1"}, headers=headers)
    assert r.status_code == 429


# --- Personal meanings -------------------------------------------------------

def test_personal_meanings_require_auth(fresh_db):
    r = client.get("/personal-meanings")
    assert r.status_code == 401


def test_save_and_list_personal_meaning(fresh_db):
    headers = _auth_headers(_signup()["token"])
    r = client.put("/personal-meanings", json={
        "subject_type": "symbol", "subject_label": "Water",
        "meaning": "Water reminds me of moving to a new city.",
    }, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subject_key"] == "water"
    assert body["meaning"] == "Water reminds me of moving to a new city."

    r = client.get("/personal-meanings", headers=headers)
    assert len(r.json()) == 1


def test_save_personal_meaning_rejects_unknown_subject_type(fresh_db):
    headers = _auth_headers(_signup()["token"])
    r = client.put("/personal-meanings", json={
        "subject_type": "vibe", "subject_label": "Water", "meaning": "x",
    }, headers=headers)
    assert r.status_code == 400


def test_save_personal_meaning_rejects_empty_meaning(fresh_db):
    headers = _auth_headers(_signup()["token"])
    r = client.put("/personal-meanings", json={
        "subject_type": "symbol", "subject_label": "Water", "meaning": "   ",
    }, headers=headers)
    assert r.status_code == 400


def test_delete_personal_meaning(fresh_db):
    headers = _auth_headers(_signup()["token"])
    client.put("/personal-meanings", json={
        "subject_type": "symbol", "subject_label": "Water", "meaning": "x",
    }, headers=headers)
    r = client.delete("/personal-meanings/symbol/water", headers=headers)
    assert r.status_code == 200
    assert client.get("/personal-meanings", headers=headers).json() == []


def test_personal_meanings_scoped_per_user(fresh_db):
    alice_headers = _auth_headers(_signup("alice")["token"])
    bob_headers = _auth_headers(_signup("bob")["token"])
    client.put("/personal-meanings", json={
        "subject_type": "symbol", "subject_label": "Water", "meaning": "Alice's take.",
    }, headers=alice_headers)

    assert client.get("/personal-meanings", headers=bob_headers).json() == []


# --- Connection feedback ------------------------------------------------------

def test_connection_feedback_requires_auth(fresh_db):
    r = client.get("/connections/feedback")
    assert r.status_code == 401


def test_save_and_list_connection_feedback(fresh_db):
    headers = _auth_headers(_signup()["token"])
    r = client.put("/connections/feedback", json={
        "connection_key": "symbol:water|symbol:anxiety", "status": "relevant",
    }, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "relevant"

    r = client.get("/connections/feedback", headers=headers)
    assert len(r.json()) == 1


def test_save_connection_feedback_rejects_unknown_status(fresh_db):
    headers = _auth_headers(_signup()["token"])
    r = client.put("/connections/feedback", json={
        "connection_key": "symbol:water|symbol:anxiety", "status": "nonsense",
    }, headers=headers)
    assert r.status_code == 400


def test_connection_feedback_resaves_in_place_not_as_history(fresh_db):
    headers = _auth_headers(_signup()["token"])
    client.put("/connections/feedback", json={
        "connection_key": "symbol:water|symbol:anxiety", "status": "relevant",
    }, headers=headers)
    client.put("/connections/feedback", json={
        "connection_key": "symbol:water|symbol:anxiety", "status": "not_relevant", "note": "actually unrelated",
    }, headers=headers)

    r = client.get("/connections/feedback", headers=headers)
    assert len(r.json()) == 1
    assert r.json()[0]["status"] == "not_relevant"
