"""
Stage 21 -- duplicate-safe /interpret. Real FastAPI app + real SQLite
(tests/conftest.py forces a temp local DB); only the AI provider is mocked.
"""
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

import database
import engine
import main
from tests.test_main import FAKE_EXTRACTED, _auth_headers, _interpret_result, _signup

client = TestClient(main.app)
RID = "req-aaaaaaaa-0001"


class AI:
    """Counting, optionally blocking / failing stand-in for the AI provider."""
    def __init__(self):
        self.calls = 0
        self.gate = None          # threading.Event: stream waits for it
        self.entered = threading.Event()
        self.fail = False
        self.lock = threading.Lock()


@pytest.fixture
def ai(monkeypatch, fresh_db):
    a = AI()
    monkeypatch.setattr(engine, "extract_dream_data", lambda t, emotions_reported=None: dict(FAKE_EXTRACTED))
    monkeypatch.setattr(engine, "embed_text", lambda t, input_type="document": [1.0, 0.0, 0.0])

    def stream(*args, **kw):
        with a.lock:
            a.calls += 1
        a.entered.set()
        if a.gate:
            a.gate.wait(10)
        if a.fail:
            raise RuntimeError("provider down")
        yield "A fake reading."
    monkeypatch.setattr(engine, "interpret_dream_stream", stream)
    return a


def _user(name="alice"):
    return _auth_headers(_signup(name)["token"])


def _post(h, text="I walked through a door", rid=RID, **extra):
    body = {"raw_text": text, **extra}
    if rid is not None:
        body["request_id"] = rid
    return client.post("/interpret", json=body, headers=h)


def _count(uid=None):
    rows, _ = database._execute("SELECT COUNT(*) AS c FROM dreams" + (" WHERE user_id = ?" if uid else ""), (uid,) if uid else ())
    return rows[0]["c"]


def test_first_submit_persists_once_with_request_id(ai):
    h = _user()
    r = _post(h)
    assert r.status_code == 200
    meta = _interpret_result(r)
    assert meta["id"] and ai.calls == 1
    rows, _ = database._execute("SELECT request_id FROM dreams WHERE id = ?", (meta["id"],))
    assert rows[0]["request_id"] == RID


def test_duplicate_submit_replays_without_second_ai_call_or_row(ai):
    h = _user()
    first = _interpret_result(_post(h))
    again = _post(h)
    assert again.status_code == 200
    meta = _interpret_result(again)
    assert meta["id"] == first["id"]
    assert meta["interpretation"] == first["interpretation"]
    assert ai.calls == 1
    assert _count() == 1


def test_replay_streamed_text_matches_original(ai):
    h = _user()
    a = _post(h).text
    b = _post(h).text
    assert a.split(main.STREAM_META_SEP)[0] == b.split(main.STREAM_META_SEP)[0]


def test_same_id_different_payload_conflicts(ai):
    h = _user()
    _post(h)
    r = _post(h, text="A completely different dream")
    assert r.status_code == 409 and r.json()["code"] == "idempotency_conflict"
    assert ai.calls == 1 and _count() == 1


def test_changed_emotions_is_a_conflict(ai):
    h = _user()
    _post(h, emotions_reported=["Joy"])
    r = _post(h, emotions_reported=["Joy", "Fear"])
    assert r.status_code == 409


def test_different_request_ids_are_separate_dreams(ai):
    h = _user()
    _post(h, rid="req-aaaaaaaa-0001")
    _post(h, rid="req-aaaaaaaa-0002")
    assert _count() == 2 and ai.calls == 2


def test_request_id_is_scoped_to_user(ai):
    a, b = _user("alice"), _user("bob")
    ma = _interpret_result(_post(a))
    mb = _interpret_result(_post(b))          # same id, other account: its own dream
    assert ma["id"] != mb["id"] and ai.calls == 2 and _count() == 2


def test_other_user_cannot_replay_someone_elses_result(ai):
    a, b = _user("alice"), _user("bob")
    ma = _interpret_result(_post(a, text="private dream"))
    rb = _post(b, text="bobs dream")
    assert _interpret_result(rb)["id"] != ma["id"]
    assert "private dream" not in rb.text


def test_no_request_id_keeps_legacy_behaviour(ai):
    h = _user()
    _post(h, rid=None)
    _post(h, rid=None)
    assert _count() == 2 and ai.calls == 2


def test_invalid_request_id_rejected(ai):
    h = _user()
    assert _post(h, rid="short").status_code == 400
    assert _post(h, rid="has spaces in it!").status_code == 400
    assert ai.calls == 0


def test_in_progress_returns_409_and_does_not_start_second_ai_call(ai):
    h = _user()
    ai.gate = threading.Event()
    out = {}
    t = threading.Thread(target=lambda: out.update(r=_post(h)))
    t.start()
    assert ai.entered.wait(10)
    r2 = _post(h)
    assert r2.status_code == 409 and r2.json()["code"] == "in_progress"
    ai.gate.set(); t.join(10)
    assert out["r"].status_code == 200
    assert ai.calls == 1 and _count() == 1
    # now finished: replay
    assert _interpret_result(_post(h))["id"] == _interpret_result(out["r"])["id"]


def test_concurrent_identical_submits_persist_exactly_one(ai):
    h = _user()
    ai.gate = threading.Event()
    results = []
    def go():
        results.append(_post(h))
    ts = [threading.Thread(target=go) for _ in range(8)]
    for t in ts: t.start()
    assert ai.entered.wait(10)
    time.sleep(0.4)
    ai.gate.set()
    for t in ts: t.join(15)
    codes = sorted(r.status_code for r in results)
    assert codes.count(200) == 1 and codes.count(409) == 7, codes
    assert ai.calls == 1 and _count() == 1


def test_polling_in_progress_does_not_spend_ai_budget(ai):
    h = _user()
    ai.gate = threading.Event()
    t = threading.Thread(target=lambda: _post(h)); t.start()
    assert ai.entered.wait(10)
    for _ in range(60):                         # far past the 40/hour budget
        assert _post(h).status_code == 409
    ai.gate.set(); t.join(10)
    assert _post(h, rid="req-aaaaaaaa-0009").status_code == 200   # budget intact


def test_replay_does_not_spend_ai_budget(ai):
    h = _user()
    _post(h)
    for _ in range(60):
        assert _post(h).status_code == 200


def test_ai_failure_releases_claim_and_retry_succeeds(ai):
    h = _user()
    ai.fail = True
    r = _post(h)
    assert "error" in _interpret_result(r) and _count() == 0
    ai.fail = False
    meta = _interpret_result(_post(h))
    assert meta["id"] and _count() == 1 and ai.calls == 2


def test_failure_before_streaming_releases_claim(ai, monkeypatch):
    h = _user()
    monkeypatch.setattr(engine, "extract_dream_data", lambda t, emotions_reported=None: (_ for _ in ()).throw(RuntimeError("extract down")))
    with pytest.raises(Exception):
        _post(h)
    assert database._execute("SELECT COUNT(*) AS c FROM dream_submissions")[0][0]["c"] == 0
    monkeypatch.setattr(engine, "extract_dream_data", lambda t, emotions_reported=None: dict(FAKE_EXTRACTED))
    assert _post(h).status_code == 200 and _count() == 1


def test_rate_limit_rejection_releases_claim(ai):
    h = _user()
    for i in range(40):
        assert _post(h, rid=f"req-bbbbbbbb-{i:04d}").status_code == 200
    assert _post(h, rid="req-bbbbbbbb-9999").status_code == 429
    assert database._execute("SELECT COUNT(*) AS c FROM dream_submissions WHERE request_id = ?", ("req-bbbbbbbb-9999",))[0][0]["c"] == 0


def test_client_disconnect_mid_stream_releases_claim(ai):
    h = _user()
    _start_and_abandon(h)             # drive the endpoint, drop the "socket" mid-stream
    assert database._execute("SELECT COUNT(*) AS c FROM dream_submissions")[0][0]["c"] == 0
    assert _post(h).status_code == 200 and _count() == 1


def _start_and_abandon(h):
    import asyncio
    holder = {}
    class Req:
        class state: request_id = "t"
    token = h["Authorization"].split()[1]
    resp = main.interpret(main.DreamIn(raw_text="I walked through a door", request_id=RID), Req, authorization="Bearer " + token)
    async def drive():
        gen = resp.body_iterator
        await gen.__anext__()                   # first chunk goes out...
        await gen.aclose()                      # ...then the client is gone
    asyncio.run(drive())
    return resp


def test_stale_processing_claim_is_taken_over_once(ai):
    h = _user()
    uid = database._execute("SELECT MAX(id) AS i FROM users")[0][0]["i"]
    ph = main.hashlib.sha256(json.dumps(["I walked through a door", None, None, []], ensure_ascii=False).encode()).hexdigest()
    dead = database.claim_submission(uid, RID, ph)
    assert dead["state"] == "claimed"
    assert database.claim_submission(uid, RID, ph)["state"] == "processing"        # fresh: not stealable
    database._execute("UPDATE dream_submissions SET updated_at = '2000-01-01T00:00:00'")  # server "died" long ago
    taker = database.claim_submission(uid, RID, ph)
    assert taker["state"] == "claimed" and taker["owner"] != dead["owner"]
    assert database.claim_submission(uid, RID, ph)["state"] == "processing"        # only one taker
    database.finish_submission(uid, RID, dead["owner"], 1, "{}")                   # dead owner is fenced out
    assert database._get_submission(uid, RID)["status"] == "processing"


def test_crash_after_dream_insert_replays_from_dream_row(ai):
    h = _user()
    meta = _interpret_result(_post(h))
    # simulate crash before the coordination row was marked done
    database._execute("UPDATE dream_submissions SET status='processing', result_json=NULL, dream_id=NULL")
    r = _post(h)
    assert r.status_code == 200 and _interpret_result(r)["id"] == meta["id"]
    assert ai.calls == 1 and _count() == 1


def test_unique_index_blocks_second_row_at_db_level(ai):
    h = _user()
    uid = database._execute("SELECT MAX(id) AS i FROM users")[0][0]["i"]
    database.insert_dream(uid, "a", dict(FAKE_EXTRACTED), "r", [1.0], request_id="req-cccccccc-0001")
    with pytest.raises(Exception) as e:
        database.insert_dream(uid, "a", dict(FAKE_EXTRACTED), "r", [1.0], request_id="req-cccccccc-0001")
    assert database.is_unique_violation(e.value)
    database.insert_dream(uid, "a", dict(FAKE_EXTRACTED), "r", [1.0])      # NULL ids never collide
    database.insert_dream(uid, "a", dict(FAKE_EXTRACTED), "r", [1.0])
    assert _count() == 3


def test_replay_after_dream_deleted_does_not_resurrect(ai):
    h = _user()
    meta = _interpret_result(_post(h))
    assert client.delete(f"/dreams/{meta['id']}", headers=h).status_code in (200, 204)
    r = _post(h)
    assert r.status_code == 409 and r.json()["code"] == "already_deleted"
    assert _count() == 0 and ai.calls == 1


def test_migration_is_additive_and_idempotent(ai):
    h = _user()
    _post(h)
    database.init_db(); database.init_db()                 # re-running changes nothing
    assert _count() == 1
    cols = {r["name"] for r in database._execute("PRAGMA table_info(dreams)")[0]}
    assert {"request_id", "raw_text", "interpretation", "emotions_reported", "emotions_plutchik"} <= cols


def test_health_advertises_idempotent_interpret(ai):
    assert "idempotent_interpret" in client.get("/health").json()["features"]


def test_upgrade_from_pre_stage21_database_keeps_every_existing_dream(ai):
    """Real migration: roll the schema back to its pre-Stage-21 shape with
    legacy single- and multi-emotion dreams in it, run init_db(), and make
    sure nothing is lost and every read endpoint still works."""
    h = _user("legacy")
    uid = database._execute("SELECT MAX(id) AS i FROM users")[0][0]["i"]
    legacy_a = dict(FAKE_EXTRACTED, emotions_plutchik=["Joy"])
    legacy_b = dict(FAKE_EXTRACTED, emotions_plutchik=["Fear", "Trust", "Sadness"])
    a = database.insert_dream(uid, "old dream one", legacy_a, "reading one", [1.0, 0.0], emotions_reported=["Joy"])
    b = database.insert_dream(uid, "old dream two", legacy_b, "reading two", [0.0, 1.0], emotions_reported=["Fear", "Hopeful", "Sadness"])
    database._execute("DROP INDEX IF EXISTS idx_dreams_user_request")
    database._execute("ALTER TABLE dreams DROP COLUMN request_id")
    database._execute("DROP TABLE dream_submissions")

    database.init_db()                                          # the upgrade

    dreams = {d["id"]: d for d in client.get("/dreams", headers=h).json()}
    assert dreams[a]["raw_text"] == "old dream one" and dreams[a]["emotions_reported"] == ["Joy"]
    assert dreams[b]["emotions_reported"] == ["Fear", "Hopeful", "Sadness"]
    assert dreams[b]["emotions_plutchik"] == ["Fear", "Trust", "Sadness"]
    assert database._execute("SELECT request_id FROM dreams WHERE id = ?", (a,))[0][0]["request_id"] is None
    # and the new path works on the upgraded database
    assert _post(h).status_code == 200 and _post(h).status_code == 200 and _count() == 3


def test_account_deletion_removes_submission_rows(ai):
    h = _user("gone")
    _post(h)
    uid = database._execute("SELECT MAX(id) AS i FROM users")[0][0]["i"]
    database.delete_account(uid)
    assert database._execute("SELECT COUNT(*) AS c FROM dream_submissions WHERE user_id = ?", (uid,))[0][0]["c"] == 0
