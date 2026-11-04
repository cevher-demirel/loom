"""Stage 24f -- confirming a person the extraction missed (the October 31 barber-shop dream), real sqlite."""
import pytest

import database
import engine
import main
from tests.test_main import FAKE_EXTRACTED, client, mock_engine, _signup, _auth_headers  # noqa: F401


def _dream(user, monkeypatch, text, people=(), symbols=()):
    monkeypatch.setattr(engine, "extract_dream_data", lambda raw, emotions_reported=None: dict(
        FAKE_EXTRACTED, people=list(people), symbols=list(symbols), settings=[], symbol_icons={s: "scissors" for s in symbols}))
    r = client.post("/interpret", json={"raw_text": text}, headers=_auth_headers(user["token"]))
    assert r.status_code == 200
    return max(d["id"] for d in database.get_all_dreams(user["id"]))


def _setup(monkeypatch):
    u = _signup("synthetic24f")
    oct31 = _dream(u, monkeypatch, "I came into Barber shop for haircut and my brother owned the shop and he was a barber.", symbols=["haircut"])
    nov3 = _dream(u, monkeypatch, "I was in a barber shop with bunch of people. This time my brother were sitting on the chair.", people=["Brother"], symbols=["barber chair"])
    other = _dream(u, monkeypatch, "I saw a red bicycle in a field.", symbols=["bicycle"])
    return u, oct31, nov3, other


def _list(u):
    r = client.get("/dreams", headers=_auth_headers(u["token"]))
    assert r.status_code == 200
    return {d["id"]: d for d in r.json()}


def test_confirming_a_missed_person_is_persisted_overlaid_and_reversible(fresh_db, mock_engine, monkeypatch):
    u, oct31, nov3, other = _setup(monkeypatch)
    before = _list(u)
    assert before[oct31]["people"] == [] and before[oct31]["confirmed_people"] == []
    stored_before = database.get_dream(u["id"], oct31)

    h = _auth_headers(u["token"])
    assert client.put("/entity-confirmations", json={"dream_id": oct31, "label": "my brother"}, headers=h).status_code == 200
    assert client.put("/entity-confirmations", json={"dream_id": oct31, "label": "Brother"}, headers=h).status_code == 200   # idempotent

    after = _list(u)
    assert after[oct31]["people"] == ["Brother"] and after[oct31]["confirmed_people"] == ["Brother"]
    assert after[nov3]["people"] == ["Brother"] and after[nov3]["confirmed_people"] == []      # extracted, not "confirmed"
    assert after[other]["people"] == [] and after[other]["confirmed_people"] == []              # unrelated dream untouched
    # both dreams now feed the one Brother concept; the unrelated one does not
    assert len(main._concept_occurrences(u["id"], "person", "person:brother")) == 2
    # the stored dream is NOT modified (text, interpretation, extraction)
    stored_after = database.get_dream(u["id"], oct31)
    for k in ("raw_text", "interpretation", "people", "symbols", "settings", "embedding"):
        assert stored_after[k] == stored_before[k]
    # reversible
    assert client.delete("/entity-confirmations", params={"dream_id": oct31, "label": "Brother"}, headers=h).status_code == 200
    assert _list(u)[oct31]["people"] == []
    assert len(main._concept_occurrences(u["id"], "person", "person:brother")) == 1


def test_confirmation_when_already_extracted_adds_no_duplicate(fresh_db, mock_engine, monkeypatch):
    u, oct31, nov3, other = _setup(monkeypatch)
    client.put("/entity-confirmations", json={"dream_id": nov3, "label": "brother"}, headers=_auth_headers(u["token"]))
    assert _list(u)[nov3]["people"] == ["Brother"]


def test_users_are_isolated_and_inputs_validated(fresh_db, mock_engine, monkeypatch):
    u, oct31, nov3, other = _setup(monkeypatch)
    mallory = _signup("mallory24f")
    hm = _auth_headers(mallory["token"])
    assert client.put("/entity-confirmations", json={"dream_id": oct31, "label": "Brother"}, headers=hm).status_code == 404
    assert client.get("/entity-confirmations", headers=hm).json() == []
    hu = _auth_headers(u["token"])
    assert client.put("/entity-confirmations", json={"dream_id": oct31, "label": ""}, headers=hu).status_code == 400
    assert client.put("/entity-confirmations", json={"dream_id": oct31, "label": "x" * 61}, headers=hu).status_code == 400
    assert client.put("/entity-confirmations", json={"dream_id": oct31, "label": "Door", "category": "symbol"}, headers=hu).status_code == 400
    assert client.get("/entity-confirmations").status_code in (401, 403)


def test_confirmations_are_removed_with_the_dream_and_with_the_account(fresh_db, mock_engine, monkeypatch):
    u, oct31, nov3, other = _setup(monkeypatch)
    h = _auth_headers(u["token"])
    client.put("/entity-confirmations", json={"dream_id": oct31, "label": "Brother"}, headers=h)
    client.put("/entity-confirmations", json={"dream_id": other, "label": "Sister"}, headers=h)
    assert len(database.list_entity_confirmations(u["id"])) == 2
    assert client.delete("/dreams/%d" % oct31, headers=h).status_code == 200
    assert [c["dream_id"] for c in database.list_entity_confirmations(u["id"])] == [other]
    database.delete_account(u["id"])
    assert database.list_entity_confirmations(u["id"]) == []


def test_dreams_still_load_if_the_confirmations_table_is_unreadable(fresh_db, mock_engine, monkeypatch):
    """SEV-1 hardening: the optional overlay can never take the journal down."""
    u, oct31, nov3, other = _setup(monkeypatch)
    def boom(_uid):
        raise RuntimeError("no such table: entity_confirmations")
    monkeypatch.setattr(database, "list_entity_confirmations", boom)
    r = client.get("/dreams", headers=_auth_headers(u["token"]))
    assert r.status_code == 200 and len(r.json()) == 3
