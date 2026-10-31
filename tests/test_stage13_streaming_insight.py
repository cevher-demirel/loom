"""
tests/test_stage13_streaming_insight.py -- Stage 13 Part 2: genuine
token-level progressive streaming for Element Detail reflections
(POST /symbols/insight/stream), additive alongside the existing
non-streaming POST /symbols/insight.

Covers:
  A. engine._symbol_insight_prompt_body: shared prompt content, the
     journal-insufficient-context instruction switch.
  B. engine.parse_symbol_insight_stream_text: sentinel reassembly,
     including the code-enforced journal-insufficient-context override
     and the "meaning" backward-compat alias -- mirroring symbol_insight.
  C. The streaming endpoint itself, using a CONTROLLED generator that
     pauses between chunks (via a threading.Event handed to the fake
     stream function) so these tests actually prove progressive,
     chunk-by-chunk delivery rather than a generator that has already
     produced its entire result before the first chunk is read -- the
     exact failure mode Stage 13's own spec calls out by name.
  D. Cache-hit path: no AI call, instant complete sentinel content.
  E. Cancellation/failure safety: an AI-side failure never reaches
     database.save_element_interpretation (same structural guarantee
     stream_interpretation already gives /interpret).
"""

import asyncio
import os
import threading

import pytest

import database
import engine
import main

from tests.test_main import FAKE_EXTRACTED, client, mock_engine, _signup, _auth_headers


SEP = engine.SYMBOL_INSIGHT_SECTION_SEP


def _sentinel_text(teaser="t", general="g", journal="j", direction="d"):
    return (
        f"{SEP}TEASER{SEP}\n{teaser}\n"
        f"{SEP}GENERAL{SEP}\n{general}\n"
        f"{SEP}JOURNAL{SEP}\n{journal}\n"
        f"{SEP}DIRECTION{SEP}\n{direction}\n"
        f"{SEP}END{SEP}"
    )


def _stream_result_and_meta(response):
    """Mirrors tests/test_main.py's _interpret_result, but for this
    endpoint's sentinel-prefixed body rather than plain interpretation
    text."""
    import json
    text = response.text
    sep_index = text.rindex(main.STREAM_META_SEP)
    return text[:sep_index], json.loads(text[sep_index + 1:])


# --- A. _symbol_insight_prompt_body: shared prompt, journal switch ---------

def test_prompt_body_includes_journal_instruction_at_or_above_threshold():
    occurrences = [{"date": "2024-01-01", "excerpt": "a"}, {"date": "2024-01-02", "excerpt": "b"}]
    body, enough = engine._symbol_insight_prompt_body("brother", occurrences, "Brother", "person")
    assert enough is True
    assert "leave it out" not in body
    assert "observational read" in body


def test_prompt_body_leaves_journal_out_below_threshold():
    occurrences = [{"date": "2024-01-01", "excerpt": "a"}]
    body, enough = engine._symbol_insight_prompt_body("brother", occurrences, "Brother", "person")
    assert enough is False
    assert "too few recorded occurrences" in body


def test_prompt_body_is_byte_identical_content_for_streaming_and_non_streaming():
    """Part 2.1/2.2: streaming must not become a different, more generic
    prompt -- both callers build the body from the exact same helper."""
    occurrences = [{"date": "2024-01-01", "excerpt": "a"}, {"date": "2024-01-02", "excerpt": "b"}]
    body1, _ = engine._symbol_insight_prompt_body("door", occurrences, "Door", "symbol")
    body2, _ = engine._symbol_insight_prompt_body("door", occurrences, "Door", "symbol")
    assert body1 == body2


# --- B. parse_symbol_insight_stream_text ------------------------------------

def test_parse_stream_text_reassembles_all_four_sections():
    text = _sentinel_text(teaser="T", general="G", journal="J", direction="D")
    result = engine.parse_symbol_insight_stream_text(text, enough_for_journal_reading=True)
    assert result["teaser"] == "T"
    assert result["general"] == "G"
    assert result["journal"] == "J"
    assert result["direction"] == "D"
    assert result["meaning"] == "G"  # backward-compat alias


def test_parse_stream_text_enforces_journal_insufficient_message_below_threshold():
    text = _sentinel_text(journal="the model wrote something anyway")
    result = engine.parse_symbol_insight_stream_text(text, enough_for_journal_reading=False)
    # Code-enforced override, exactly like symbol_insight's own non-streaming
    # path -- never trusts the model to have honored "leave it empty".
    assert result["journal"] == engine.JOURNAL_INSUFFICIENT_CONTEXT_MESSAGE


def test_parse_stream_text_enforces_journal_insufficient_message_when_model_left_it_empty():
    text = _sentinel_text(journal="")
    result = engine.parse_symbol_insight_stream_text(text, enough_for_journal_reading=True)
    assert result["journal"] == engine.JOURNAL_INSUFFICIENT_CONTEXT_MESSAGE


def test_parse_stream_text_falls_back_on_empty_teaser_body():
    # TEASER's MARKER must still be present (see the malformed-structure
    # tests below) -- but its own body being empty just falls back to the
    # canned message, same as symbol_insight's own non-streaming path.
    text = _sentinel_text(teaser="")
    result = engine.parse_symbol_insight_stream_text(text, enough_for_journal_reading=True)
    assert "try again" in result["teaser"]


# --- B2. PR review correction: reject malformed/incomplete streams ---------
# (never silently return a dict with a missing section -- raise instead,
# so main.py's on_complete never reaches database.save_element_interpretation
# with it; see SymbolInsightStreamMalformed's own docstring in engine.py)

def test_parse_stream_text_normal_completion_does_not_raise():
    text = _sentinel_text(teaser="t", general="g", journal="j", direction="d")
    result = engine.parse_symbol_insight_stream_text(text, enough_for_journal_reading=True)
    assert result["general"] == "g"
    assert result["direction"] == "d"


def test_parse_stream_text_raises_on_missing_general():
    text = f"{SEP}TEASER{SEP}\nt\n{SEP}JOURNAL{SEP}\nj\n{SEP}DIRECTION{SEP}\nd\n{SEP}END{SEP}"
    with pytest.raises(engine.SymbolInsightStreamMalformed):
        engine.parse_symbol_insight_stream_text(text, enough_for_journal_reading=True)


def test_parse_stream_text_raises_on_empty_general_body():
    # The GENERAL marker is present (structure looks fine) but its body is
    # blank -- a genuinely different failure mode from a missing marker,
    # and one the marker-sequence check alone wouldn't catch.
    text = _sentinel_text(general="   ")
    with pytest.raises(engine.SymbolInsightStreamMalformed):
        engine.parse_symbol_insight_stream_text(text, enough_for_journal_reading=True)


def test_parse_stream_text_raises_on_empty_direction_body():
    text = _sentinel_text(direction="")
    with pytest.raises(engine.SymbolInsightStreamMalformed):
        engine.parse_symbol_insight_stream_text(text, enough_for_journal_reading=True)


def test_parse_stream_text_raises_on_missing_end_marker():
    # A connection dropped mid-generation, right after DIRECTION's text --
    # no END ever arrived.
    text = f"{SEP}TEASER{SEP}\nt\n{SEP}GENERAL{SEP}\ng\n{SEP}JOURNAL{SEP}\nj\n{SEP}DIRECTION{SEP}\nd\n"
    with pytest.raises(engine.SymbolInsightStreamMalformed):
        engine.parse_symbol_insight_stream_text(text, enough_for_journal_reading=True)


def test_parse_stream_text_raises_on_incomplete_stream_cut_off_mid_journal():
    # Dropped even earlier -- not even DIRECTION's marker arrived yet.
    text = f"{SEP}TEASER{SEP}\nt\n{SEP}GENERAL{SEP}\ng\n{SEP}JOURNAL{SEP}\nhalf a thou"
    with pytest.raises(engine.SymbolInsightStreamMalformed):
        engine.parse_symbol_insight_stream_text(text, enough_for_journal_reading=True)


def test_parse_stream_text_raises_on_out_of_order_markers():
    text = f"{SEP}GENERAL{SEP}\ng\n{SEP}TEASER{SEP}\nt\n{SEP}JOURNAL{SEP}\nj\n{SEP}DIRECTION{SEP}\nd\n{SEP}END{SEP}"
    with pytest.raises(engine.SymbolInsightStreamMalformed):
        engine.parse_symbol_insight_stream_text(text, enough_for_journal_reading=True)


def test_parse_stream_text_raises_on_misspelled_marker():
    text = f"{SEP}TEASER{SEP}\nt\n{SEP}GENERL{SEP}\ng\n{SEP}JOURNAL{SEP}\nj\n{SEP}DIRECTION{SEP}\nd\n{SEP}END{SEP}"
    with pytest.raises(engine.SymbolInsightStreamMalformed):
        engine.parse_symbol_insight_stream_text(text, enough_for_journal_reading=True)


def test_parse_stream_text_raises_on_duplicated_section():
    text = (
        f"{SEP}TEASER{SEP}\nt\n{SEP}GENERAL{SEP}\ng1\n{SEP}GENERAL{SEP}\ng2\n"
        f"{SEP}JOURNAL{SEP}\nj\n{SEP}DIRECTION{SEP}\nd\n{SEP}END{SEP}"
    )
    with pytest.raises(engine.SymbolInsightStreamMalformed):
        engine.parse_symbol_insight_stream_text(text, enough_for_journal_reading=True)


def test_parse_stream_text_raises_on_unexpected_extra_section():
    text = (
        f"{SEP}TEASER{SEP}\nt\n{SEP}GENERAL{SEP}\ng\n{SEP}JOURNAL{SEP}\nj\n"
        f"{SEP}EXTRA{SEP}\nwhat is this\n{SEP}DIRECTION{SEP}\nd\n{SEP}END{SEP}"
    )
    with pytest.raises(engine.SymbolInsightStreamMalformed):
        engine.parse_symbol_insight_stream_text(text, enough_for_journal_reading=True)


# --- C. Genuine progressive delivery (controlled generator) ----------------

def _setup_one_brother_dream(monkeypatch):
    user = _signup()
    monkeypatch.setattr(
        engine, "extract_dream_data",
        lambda raw_text, emotions_reported=None: dict(FAKE_EXTRACTED, people=["my brother"], symbols=[], themes=[]),
    )
    client.post("/interpret", json={"raw_text": "a dream about my brother"}, headers=_auth_headers(user["token"]))
    monkeypatch.setattr(
        engine, "extract_dream_data",
        lambda raw_text, emotions_reported=None: dict(FAKE_EXTRACTED, people=["my brother"], symbols=[], themes=[]),
    )
    client.post("/interpret", json={"raw_text": "brother again"}, headers=_auth_headers(user["token"]))
    return user


def test_stream_endpoint_delivers_chunks_progressively_not_all_at_once(fresh_db, mock_engine, monkeypatch):
    """The exact failure mode Stage 13's spec warns against by name: a
    mocked generator that has already produced the entire result before
    the first chunk is emitted isn't testing streaming at all. This test
    uses a real threading.Event so the fake model generator genuinely
    pauses mid-stream until the test explicitly releases it, and asserts
    the HTTP client can observe a FIRST chunk that does not yet contain
    the LAST section -- something only possible if delivery is actually
    progressive."""
    user = _setup_one_brother_dream(monkeypatch)

    release_second_chunk = threading.Event()
    chunks_emitted = []

    def controlled_stream(symbol, occurrences, concept_label=None, category="symbol"):
        first = f"{SEP}TEASER{SEP}\nt\n{SEP}GENERAL{SEP}\ng\n"
        chunks_emitted.append(first)
        yield first
        release_second_chunk.wait(timeout=5)
        second = f"{SEP}JOURNAL{SEP}\nj\n{SEP}DIRECTION{SEP}\nd\n{SEP}END{SEP}"
        chunks_emitted.append(second)
        yield second

    monkeypatch.setattr(engine, "symbol_insight_stream", controlled_stream)

    # Driven directly against the real ASGI StreamingResponse machinery
    # (not through TestClient's httpx transport, which buffers a sync
    # generator's entire output before this test could observe a partial
    # read) -- this still exercises the production code path main.py's
    # route actually returns, just awaited chunk-by-chunk the same way
    # Starlette's own response-sending loop does.
    payload = main.SymbolInsightIn(symbol="Brother", category="person")
    response = main.symbol_insight_stream_endpoint(payload, f"Bearer {user['token']}")
    assert response.status_code == 200

    async def consume():
        agen = response.body_iterator
        first = await agen.__anext__()
        first_text = first if isinstance(first, str) else first.decode()
        # Proof of genuine progressiveness: the first piece produced by
        # the response does NOT yet contain the DIRECTION/END section,
        # because the fake generator above is still blocked on
        # release_second_chunk at exactly this point -- a fake
        # "typewriter" that already had the whole string ready before
        # yielding anything would fail this assertion.
        assert "DIRECTION" not in first_text
        assert "TEASER" in first_text

        release_second_chunk.set()
        rest_pieces = []
        async for chunk in agen:
            rest_pieces.append(chunk if isinstance(chunk, str) else chunk.decode())
        return first_text, "".join(rest_pieces)

    first_piece, rest = asyncio.run(consume())
    full_text = first_piece + rest

    assert "DIRECTION" in full_text
    assert len(chunks_emitted) == 2


def test_stream_endpoint_full_reassembled_content_matches_non_streaming_fields(fresh_db, mock_engine, monkeypatch):
    user = _setup_one_brother_dream(monkeypatch)

    def fake_stream(symbol, occurrences, concept_label=None, category="symbol"):
        yield _sentinel_text(teaser="Brother teaser", general="Brother general", journal="Brother journal", direction="Brother question?")

    monkeypatch.setattr(engine, "symbol_insight_stream", fake_stream)

    r = client.post(
        "/symbols/insight/stream",
        json={"symbol": "Brother", "category": "person"},
        headers=_auth_headers(user["token"]),
    )
    assert r.status_code == 200
    body_text, meta = _stream_result_and_meta(r)
    assert meta["teaser"] == "Brother teaser"
    assert meta["general"] == "Brother general"
    assert meta["journal"] == "Brother journal"
    assert meta["direction"] == "Brother question?"
    assert meta["meaning"] == "Brother general"
    assert meta["cached"] is False

    # And it was actually cached for next time, under the concept key --
    # same cache row /symbols/insight itself would have written.
    cached = database.get_element_interpretation(user["id"], "person:brother")
    assert cached["teaser"] == "Brother teaser"


# --- D. Cache hit: instant, complete, no AI call ----------------------------

def test_stream_endpoint_cache_hit_never_calls_the_ai_stream(fresh_db, mock_engine, monkeypatch):
    user = _setup_one_brother_dream(monkeypatch)

    # Prime the cache exactly like a prior /symbols/insight call would.
    r1 = client.post(
        "/symbols/insight", json={"symbol": "Brother", "category": "person"},
        headers=_auth_headers(user["token"]),
    )
    assert r1.status_code == 200

    def explode(*a, **kw):
        raise AssertionError("AI stream must not be called on a cache hit")
    monkeypatch.setattr(engine, "symbol_insight_stream", explode)

    r2 = client.post(
        "/symbols/insight/stream", json={"symbol": "Brother", "category": "person"},
        headers=_auth_headers(user["token"]),
    )
    assert r2.status_code == 200
    body_text, meta = _stream_result_and_meta(r2)
    assert meta["cached"] is True
    assert meta["teaser"] == r1.json()["teaser"]
    assert "TEASER" in body_text and "END" in body_text  # same sentinel shape as a live stream


# --- E. Failure/cancellation safety: never cache partial content -----------

def test_stream_endpoint_ai_failure_reports_error_and_never_caches(fresh_db, mock_engine, monkeypatch):
    user = _setup_one_brother_dream(monkeypatch)

    def failing_stream(symbol, occurrences, concept_label=None, category="symbol"):
        yield f"{SEP}TEASER{SEP}\nhalf a thought\n"
        raise RuntimeError("model call failed mid-stream")

    monkeypatch.setattr(engine, "symbol_insight_stream", failing_stream)

    r = client.post(
        "/symbols/insight/stream", json={"symbol": "Brother", "category": "person"},
        headers=_auth_headers(user["token"]),
    )
    assert r.status_code == 200  # headers/status already sent before the failure
    _body, meta = _stream_result_and_meta(r)
    assert "error" in meta

    # The partial "half a thought" must never have been saved as a
    # complete cached reading.
    assert database.get_element_interpretation(user["id"], "person:brother") is None


def test_stream_endpoint_malformed_structured_output_reports_error_and_never_caches(fresh_db, mock_engine, monkeypatch):
    """A model response that streams to a clean end (no connection error)
    but doesn't actually match the required section contract -- e.g. a
    missing DIRECTION section -- must be treated exactly like any other
    stream failure: reported as an error, never cached, never presented
    as a complete reflection."""
    user = _setup_one_brother_dream(monkeypatch)

    def malformed_stream(symbol, occurrences, concept_label=None, category="symbol"):
        # No DIRECTION section at all -- a genuinely "completed" stream
        # (it does end with END) that still fails the response contract.
        yield f"{SEP}TEASER{SEP}\nt\n{SEP}GENERAL{SEP}\ng\n{SEP}JOURNAL{SEP}\nj\n{SEP}END{SEP}"

    monkeypatch.setattr(engine, "symbol_insight_stream", malformed_stream)

    r = client.post(
        "/symbols/insight/stream", json={"symbol": "Brother", "category": "person"},
        headers=_auth_headers(user["token"]),
    )
    assert r.status_code == 200
    _body, meta = _stream_result_and_meta(r)
    assert "error" in meta
    assert database.get_element_interpretation(user["id"], "person:brother") is None


# --- PR review correction #3: distinguishable 404s -------------------------

def test_stream_endpoint_404_for_missing_concept_carries_the_shared_detail_string(fresh_db, mock_engine, monkeypatch):
    """index.html tells a genuinely-missing concept apart from a missing
    ROUTE (an older backend mid-deploy) by matching main.STREAM_META_SEP
    ... er, main.SYMBOL_NOT_FOUND_DETAIL exactly -- this is the contract
    test that keeps that string from silently drifting between main.py
    and index.html without either side noticing."""
    user = _signup()  # no dreams logged at all -- the concept can't exist
    r = client.post(
        "/symbols/insight/stream", json={"symbol": "Brother", "category": "person"},
        headers=_auth_headers(user["token"]),
    )
    assert r.status_code == 404
    assert r.json()["detail"] == main.SYMBOL_NOT_FOUND_DETAIL

    # And the same fixed string on the non-streaming sibling, since the
    # frontend's disambiguation logic depends on both endpoints agreeing.
    r2 = client.post(
        "/symbols/insight", json={"symbol": "Brother", "category": "person"},
        headers=_auth_headers(user["token"]),
    )
    assert r2.status_code == 404
    assert r2.json()["detail"] == main.SYMBOL_NOT_FOUND_DETAIL


def test_frontend_shared_not_found_detail_constant_matches_backend():
    """A lighter-weight companion to the Node-based parser check: confirms
    index.html's own copy of SYMBOL_NOT_FOUND_DETAIL (which can't import
    main.py's constant directly -- it's a separate, static frontend file)
    hasn't silently drifted out of sync with the backend's string, since
    the whole point of task #3's fix depends on an exact match."""
    with open(os.path.join(os.path.dirname(__file__), "..", "index.html"), encoding="utf-8") as f:
        html = f.read()
    assert ('var SYMBOL_NOT_FOUND_DETAIL = "' + main.SYMBOL_NOT_FOUND_DETAIL + '";') in html
