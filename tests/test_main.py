"""
tests/test_main.py -- integration tests for main.py's HTTP endpoints,
using FastAPI's own TestClient (so these go through real routing,
auth, and request/response validation, not just calling functions
directly).

Every Claude and Voyage call is mocked via the mock_engine fixture
below -- this suite costs nothing to run and needs no API keys, and
more importantly, a test suite that calls a real LLM isn't actually
testing the same thing twice in a row (that's what evals/ is for, see
its own README). What's under test here is Loom's own code: routing,
auth, ownership checks, and response shapes.
"""

import pytest
from fastapi.testclient import TestClient

import database
import engine
import main

client = TestClient(main.app)

FAKE_EXTRACTED = {
    "symbols": ["a door"],
    "emotions": ["curiosity"],
    "people": [],
    "settings": ["a hallway"],
    "themes": ["transition"],
}


@pytest.fixture
def mock_engine(monkeypatch):
    """Stub out every Claude/Voyage call engine.py makes, so endpoint
    tests exercise Loom's own routing and database logic without a
    network call or an API key."""
    monkeypatch.setattr(engine, "extract_dream_data", lambda raw_text: dict(FAKE_EXTRACTED))
    monkeypatch.setattr(engine, "embed_text", lambda text, input_type="document": [1.0, 0.0, 0.0])
    monkeypatch.setattr(engine, "interpret_dream", lambda raw_text, extracted, similar=None, profile=None, location=None, dream_timestamp=None: "A fake reading.")
    monkeypatch.setattr(engine, "continue_conversation", lambda messages, profile=None, related_dreams=None, search_fn=None, dream_timestamp=None: "A fake reply.")
    monkeypatch.setattr(engine, "analyze_patterns", lambda all_dreams, profile=None, search_fn=None: "**Recurring symbols & themes**\n- a fake pattern")


def _signup(username="alice", password="hunter22"):
    r = client.post("/signup", json={"username": username, "password": password})
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
    r = client.post("/signup", json={"username": "alice", "password": "something-else"})
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
    body = r.json()
    assert body["interpretation"] == "A fake reading."
    assert body["symbols"] == ["a door"]

    listing = client.get("/dreams", headers=_auth_headers(user["token"]))
    assert len(listing.json()) == 1


def test_interpret_empty_text_is_400(fresh_db, mock_engine):
    user = _signup()
    r = client.post("/interpret", json={"raw_text": "   "}, headers=_auth_headers(user["token"]))
    assert r.status_code == 400


def test_edit_dream_reinterprets_it(fresh_db, mock_engine, monkeypatch):
    user = _signup()
    created = client.post("/interpret", json={"raw_text": "original"}, headers=_auth_headers(user["token"])).json()

    new_reading = "A different fake reading."
    monkeypatch.setattr(engine, "interpret_dream", lambda raw_text, extracted, similar=None, profile=None, location=None, dream_timestamp=None: new_reading)
    r = client.put(f"/dreams/{created['id']}", json={"raw_text": "edited"}, headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    assert r.json()["interpretation"] == new_reading


def test_edit_nonexistent_dream_is_404(fresh_db, mock_engine):
    user = _signup()
    r = client.put("/dreams/99999", json={"raw_text": "edited"}, headers=_auth_headers(user["token"]))
    assert r.status_code == 404


def test_delete_dream_removes_it(fresh_db, mock_engine):
    user = _signup()
    created = client.post("/interpret", json={"raw_text": "a dream"}, headers=_auth_headers(user["token"])).json()

    r = client.delete(f"/dreams/{created['id']}", headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    assert r.json() == {"deleted": True}

    listing = client.get("/dreams", headers=_auth_headers(user["token"]))
    assert listing.json() == []


def test_delete_nonexistent_dream_is_404(fresh_db, mock_engine):
    user = _signup()
    r = client.delete("/dreams/99999", headers=_auth_headers(user["token"]))
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
    created = client.post("/interpret", json={"raw_text": "alice's dream"}, headers=_auth_headers(alice["token"])).json()

    r = client.put(f"/dreams/{created['id']}", json={"raw_text": "bob tries to overwrite this"}, headers=_auth_headers(bob["token"]))
    assert r.status_code == 404  # looks the same as "doesn't exist" from bob's side -- no leak either way


def test_cannot_delete_another_users_dream_via_api(fresh_db, mock_engine):
    alice = _signup("alice")
    bob = _signup("bob")
    created = client.post("/interpret", json={"raw_text": "alice's dream"}, headers=_auth_headers(alice["token"])).json()

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
    assert r.json()["count"] == 1


# --- Agentic retrieval: search_fn actually gets wired through ---------------
# mock_engine stubs analyze_patterns/continue_conversation entirely, so it
# can't tell us whether main.py bothered to build and pass a real
# search_fn versus just leaving it None. These two tests replace the stub
# with something that inspects what it was handed instead.

def test_patterns_passes_a_working_search_fn(fresh_db, mock_engine, monkeypatch):
    user = _signup()
    client.post("/interpret", json={"raw_text": "a dream"}, headers=_auth_headers(user["token"]))

    captured = {}

    def fake_analyze(all_dreams, profile=None, search_fn=None):
        captured["search_fn"] = search_fn
        return "ok"

    monkeypatch.setattr(engine, "analyze_patterns", fake_analyze)
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
    created = client.post(
        "/interpret", json={"raw_text": "a dream"}, headers=_auth_headers(user["token"]),
    ).json()

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


# --- Guest sessions: try it out, then claim it on signup/login --------------

def test_guest_can_interpret_and_list(fresh_db, mock_engine):
    guest = client.post("/guest").json()
    r = client.post("/interpret", json={"raw_text": "a guest dream"}, headers=_auth_headers(guest["token"]))
    assert r.status_code == 200

    listing = client.get("/dreams", headers=_auth_headers(guest["token"]))
    assert len(listing.json()) == 1
    assert listing.json()[0]["raw_text"] == "a guest dream"


def test_claim_guest_dreams_on_signup_moves_them_over(fresh_db, mock_engine):
    guest = client.post("/guest").json()
    client.post("/interpret", json={"raw_text": "logged before signing up"}, headers=_auth_headers(guest["token"]))

    alice = _signup("alice")
    r = client.post(
        "/claim-guest-dreams", json={"guest_token": guest["token"]}, headers=_auth_headers(alice["token"])
    )
    assert r.status_code == 200
    assert r.json() == {"claimed": 1}

    archive = client.get("/dreams", headers=_auth_headers(alice["token"])).json()
    assert len(archive) == 1
    assert archive[0]["raw_text"] == "logged before signing up"

    # The guest account is gone -- its token no longer authenticates anything.
    assert client.get("/dreams", headers=_auth_headers(guest["token"])).status_code == 401


def test_claim_guest_dreams_on_login_also_moves_them_over(fresh_db, mock_engine):
    # Same claim path, but the guest chooses "Log In" to an existing
    # account instead of signing up fresh -- per the user's own call,
    # this should work identically either way.
    alice = _signup("alice", "hunter22")
    guest = client.post("/guest").json()
    client.post("/interpret", json={"raw_text": "guest dream, then I log in"}, headers=_auth_headers(guest["token"]))

    logged_in = client.post("/login", json={"username": "alice", "password": "hunter22"}).json()
    r = client.post(
        "/claim-guest-dreams", json={"guest_token": guest["token"]}, headers=_auth_headers(logged_in["token"])
    )
    assert r.status_code == 200
    assert r.json() == {"claimed": 1}

    archive = client.get("/dreams", headers=_auth_headers(logged_in["token"])).json()
    assert len(archive) == 1


def test_claim_guest_dreams_cannot_pull_from_a_real_account(fresh_db, mock_engine):
    # The security boundary: claim-guest-dreams only ever moves dreams
    # out of a genuine is_guest=1 row. Handing it a real account's token
    # as "guest_token" must not let bob pull alice's dreams into his own
    # account just because he somehow got hold of her token.
    alice = _signup("alice")
    client.post("/interpret", json={"raw_text": "alice's real dream"}, headers=_auth_headers(alice["token"]))
    bob = _signup("bob")

    r = client.post(
        "/claim-guest-dreams", json={"guest_token": alice["token"]}, headers=_auth_headers(bob["token"])
    )
    assert r.status_code == 200
    assert r.json() == {"claimed": 0}  # no-op, not an error -- nothing moved

    # Alice still has her dream; bob got nothing.
    assert len(client.get("/dreams", headers=_auth_headers(alice["token"])).json()) == 1
    assert client.get("/dreams", headers=_auth_headers(bob["token"])).json() == []


def test_claim_guest_dreams_needs_auth(fresh_db):
    r = client.post("/claim-guest-dreams", json={"guest_token": "whatever"})
    assert r.status_code == 401


def test_health_needs_no_auth(fresh_db):
    # Deliberately no Authorization header -- a monitoring tool can't
    # supply one, so this must never 401.
    r = client.get("/health")
    assert r.status_code == 200
