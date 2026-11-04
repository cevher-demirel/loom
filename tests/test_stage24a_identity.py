"""Stage 24a -- backend identity rules (real sqlite via the shared fixtures)."""
import pytest

import main
from tests.test_main import client, mock_engine, _signup, _auth_headers, _interpret_result  # noqa: F401


@pytest.mark.parametrize("category,raw,slug", [
    ("place", "barber shop", "barber shop"), ("place", "Barbershop", "barber shop"),
    ("place", "the barber-shop", "barber shop"), ("symbol", "A barbershop", "barber shop"),
    ("symbol", "haircut", "haircut"), ("symbol", "hair cut", "haircut"),
    ("symbol", "Hair cutting", "haircut"), ("symbol", "haircutting", "haircut"),
    ("person", "Dad", "father"), ("person", "my daddy", "father"),
])
def test_aliases_merge(category, raw, slug):
    assert main.concept_slug_for(category, raw) == slug


@pytest.mark.parametrize("category,a,b", [
    ("symbol", "barber chair", "barber shop"), ("place", "barber shop", "shop"),
    ("symbol", "haircut", "hair"), ("symbol", "haircut", "hair dye"), ("symbol", "haircut", "barber shop"),
    ("person", "brother", "father"), ("place", "barber shop", "barber shop owner"),
    ("place", "my house", "house"),
])
def test_aliases_never_merge_different_things(category, a, b):
    assert main.concept_slug_for(category, a) != main.concept_slug_for(category, b)


def test_display_labels_for_aliased_concepts():
    assert main.concept_display_label_for("place", "barbershop") == "Barber shop"
    assert main.concept_display_label_for("symbol", "hair cutting") == "Haircut"
    assert main.concept_display_label_for("place", "a hallway") == "a hallway"   # unchanged for everything else


def test_existing_slugs_unchanged_for_unlisted_labels():
    assert main.concept_slug_for("place", "My Childhood Home") == "my childhood home"
    assert main.concept_slug_for("symbol", "The door") == "door"


# --- real FastAPI + sqlite ---------------------------------------------------
import engine  # noqa: E402
from tests.test_main import FAKE_EXTRACTED  # noqa: E402


def _post(user, text, **fields):
    import tests.test_stage12_concepts as t
    return t.client.post("/interpret", json={"raw_text": text}, headers=_auth_headers(user["token"]))


def test_integration_dad_father_barbershop_counts_distinct_dreams_and_isolate_users(fresh_db, mock_engine, monkeypatch):
    a, b = _signup("alice24"), _signup("bob24")

    def extract(people=(), settings=(), symbols=()):
        return lambda raw_text, emotions_reported=None: dict(
            FAKE_EXTRACTED, people=list(people), settings=list(settings), symbols=list(symbols),
            symbol_icons={s: "scissors" for s in symbols})

    for who, text, kw in [
        (a, "dad 1", dict(people=["Dad"], settings=["barber shop"])),
        (a, "father 2", dict(people=["Father", "my dad"], settings=["Barbershop"])),     # many aliases, one dream
        (a, "brother only", dict(people=["Brother"], settings=["barber chair"])),
        (a, "text mentions dad but no tag", dict()),
        (b, "bob dad", dict(people=["Dad"], settings=["barbershop"])),
    ]:
        monkeypatch.setattr(engine, "extract_dream_data", extract(**kw))
        r = client.post("/interpret", json={"raw_text": text}, headers=_auth_headers(who["token"]))
        assert r.status_code == 200

    father = main._concept_occurrences(a["id"], "person", main.concept_key_for("person", "Dad"))
    assert len(father) == 2                                                  # distinct dreams, tags only (dream 4 is text-only)
    shop = main._concept_occurrences(a["id"], "place", main.concept_key_for("place", "Barbershop"))
    assert len(shop) == 2
    chair = main._concept_occurrences(a["id"], "place", main.concept_key_for("place", "barber chair"))
    assert len(chair) == 1                                                  # a chair is not the shop
    brother = main._concept_occurrences(a["id"], "person", "person:brother")
    assert len(brother) == 1
    assert len(main._concept_occurrences(b["id"], "person", "person:father")) == 1   # bob's data never leaks into alice's
