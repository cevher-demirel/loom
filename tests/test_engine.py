"""
tests/test_engine.py -- unit tests for the parts of engine.py that don't
call Claude or Voyage: cosine similarity math, JSON-parsing fallback,
and the similarity-filtering logic. No API key needed to run this file
and no network call happens -- these are pure functions.

The _run_tool_loop tests below are the exception -- they do touch
engine.client, but only a fake stand-in (monkeypatched onto
engine.client.messages.create), so still no real network call or API
key. What's under test there is the agentic loop's own control flow
(does it call search_dreams with what the model asked for, does it stop
at end_turn, does it give up after enough rounds) -- never real model
behavior, which is exactly what makes it fast, free, and deterministic
enough for a unit test rather than something that belongs in evals/.
"""

import math
from types import SimpleNamespace

import engine


# --- cosine_similarity --------------------------------------------------

def test_cosine_similarity_identical_vectors_is_one():
    v = [1.0, 2.0, 3.0]
    assert math.isclose(engine.cosine_similarity(v, v), 1.0, rel_tol=1e-9)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert engine.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_similarity_opposite_vectors_is_negative_one():
    assert math.isclose(engine.cosine_similarity([1.0, 0.0], [-1.0, 0.0]), -1.0, rel_tol=1e-9)


def test_cosine_similarity_mismatched_lengths_is_zero():
    assert engine.cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0


def test_cosine_similarity_empty_vector_is_zero():
    assert engine.cosine_similarity([], [1.0, 2.0]) == 0.0
    assert engine.cosine_similarity([1.0, 2.0], []) == 0.0


def test_cosine_similarity_old_word_list_embedding_is_zero_not_a_crash():
    # Dreams logged before the Voyage AI switch have a list of words
    # (strings) sitting in their embedding column instead of a real
    # vector -- this must score 0 and never raise, see the function's
    # own docstring for why.
    assert engine.cosine_similarity(["boat", "captain"], ["boat", "captain"]) == 0.0


def test_cosine_similarity_zero_vector_is_zero():
    assert engine.cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


# --- _parse_json_safely --------------------------------------------------

def test_parse_json_safely_clean_json():
    result = engine._parse_json_safely('{"symbols": ["a door"]}', {"symbols": []})
    assert result == {"symbols": ["a door"]}


def test_parse_json_safely_json_wrapped_in_markdown_fence():
    text = '```json\n{"symbols": ["a key"]}\n```'
    result = engine._parse_json_safely(text, {"symbols": []})
    assert result == {"symbols": ["a key"]}


def test_parse_json_safely_json_with_stray_prose_around_it():
    text = 'Sure, here is the data: {"symbols": ["a bridge"]} -- hope that helps!'
    result = engine._parse_json_safely(text, {"symbols": []})
    assert result == {"symbols": ["a bridge"]}


def test_parse_json_safely_completely_malformed_returns_fallback():
    fallback = {"symbols": [], "emotions": []}
    result = engine._parse_json_safely("not json at all, sorry", fallback)
    assert result == fallback


def test_parse_json_safely_recovers_from_a_literal_newline_inside_a_string_value():
    # The real failure mode this guards against: a model breaks a string
    # value across literal lines (invalid JSON -- raw newlines aren't
    # allowed inside a JSON string) even though the prompt asked it not
    # to. json.loads chokes on this directly; the recovery path collapses
    # the newline into a space and parses the result.
    text = '{"teaser": "a plain line", "meaning": "a sentence that\nkeeps going on a new line", "direction": "a question?"}'
    result = engine._parse_json_safely(text, {"teaser": "", "meaning": "", "direction": ""})
    assert result == {
        "teaser": "a plain line",
        "meaning": "a sentence that keeps going on a new line",
        "direction": "a question?",
    }


# --- find_similar_dreams --------------------------------------------------

def _dream(id_, embedding):
    return {"id": id_, "embedding": embedding, "raw_text": f"dream {id_}"}


def test_find_similar_dreams_empty_new_embedding_returns_empty():
    assert engine.find_similar_dreams([], [_dream(1, [1.0, 0.0])]) == []


def test_find_similar_dreams_skips_dreams_without_an_embedding():
    dreams = [_dream(1, []), _dream(2, [1.0, 0.0])]
    result = engine.find_similar_dreams([1.0, 0.0], dreams, top_n=3)
    assert [d["id"] for d in result] == [2]


def test_find_similar_dreams_filters_out_weak_matches():
    # Orthogonal (score 0) should never show up -- only genuinely
    # similar dreams clear the 0.3 bar.
    dreams = [_dream(1, [0.0, 1.0]), _dream(2, [1.0, 0.0])]
    result = engine.find_similar_dreams([1.0, 0.0], dreams, top_n=3)
    assert [d["id"] for d in result] == [2]


def test_find_similar_dreams_returns_most_similar_first():
    dreams = [
        _dream(1, [0.9, 0.1]),   # close, but not as close as #2
        _dream(2, [1.0, 0.0]),   # identical direction
    ]
    result = engine.find_similar_dreams([1.0, 0.0], dreams, top_n=3)
    assert [d["id"] for d in result] == [2, 1]


def test_find_similar_dreams_respects_top_n():
    dreams = [_dream(i, [1.0, 0.0]) for i in range(5)]
    result = engine.find_similar_dreams([1.0, 0.0], dreams, top_n=2)
    assert len(result) == 2


# --- _format_dream_for_tool -------------------------------------------------

def test_format_dream_for_tool_includes_tags_snippet_and_followup():
    dream = {
        "timestamp": "2026-01-15T10:00:00",
        "symbols": ["a locked door"],
        "emotions": ["frustration"],
        "themes": ["being blocked"],
        "raw_text": "I kept trying every key I had and none of them fit.",
        "conversation": [
            {"role": "user", "content": "That door was my old office."},
            {"role": "assistant", "content": "A reply that should NOT appear."},
        ],
    }
    line = engine._format_dream_for_tool(dream)
    assert "2026-01-15" in line
    assert "a locked door" in line
    assert "I kept trying every key" in line
    assert "That door was my old office." in line
    assert "should NOT appear" not in line


def test_format_dream_for_tool_handles_missing_fields():
    # A bare-minimum record (e.g. from a fallback path) should never
    # crash just because conversation/symbols/etc. are missing or empty.
    line = engine._format_dream_for_tool({"timestamp": "2026-01-01T00:00:00"})
    assert "2026-01-01" in line


# --- SEARCH_DREAMS_TOOL ------------------------------------------------------

def test_search_dreams_tool_schema_requires_query():
    assert engine.SEARCH_DREAMS_TOOL["name"] == "search_dreams"
    assert engine.SEARCH_DREAMS_TOOL["input_schema"]["required"] == ["query"]


# --- _run_tool_loop ----------------------------------------------------------

def _text_response(text, stop_reason="end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=10, output_tokens=10),
    )


def _tool_use_response(query, top_n=5, tool_use_id="toolu_1"):
    return SimpleNamespace(
        content=[SimpleNamespace(
            type="tool_use", name="search_dreams", id=tool_use_id,
            input={"query": query, "top_n": top_n},
        )],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=10, output_tokens=10),
    )


def test_run_tool_loop_returns_text_with_no_tool_call(monkeypatch):
    monkeypatch.setattr(
        engine.client.messages, "create",
        lambda **kwargs: _text_response("a direct answer, no lookup needed"),
    )
    result = engine._run_tool_loop("test_stage", "system", [{"role": "user", "content": "hi"}], None, 100)
    assert result == "a direct answer, no lookup needed"


def test_run_tool_loop_calls_search_fn_with_models_query(monkeypatch):
    calls = iter([
        _tool_use_response("falling", top_n=2),
        _text_response("final answer grounded in what search_dreams returned"),
    ])
    monkeypatch.setattr(engine.client.messages, "create", lambda **kwargs: next(calls))

    search_calls = []

    def fake_search(query, top_n=5):
        search_calls.append((query, top_n))
        return [{"timestamp": "2026-01-01T00:00:00", "symbols": ["falling"], "emotions": [], "themes": [], "raw_text": "I fell."}]

    messages = [{"role": "user", "content": "what patterns do you see?"}]
    result = engine._run_tool_loop("test_stage", "system", messages, fake_search, 100)

    assert search_calls == [("falling", 2)]
    assert result == "final answer grounded in what search_dreams returned"
    # The loop appended its own assistant/tool_result turns onto the list
    # it was given -- confirms the tool round-trip actually happened,
    # not just that search_fn got called.
    assert len(messages) == 3


def test_run_tool_loop_no_matches_tells_model_nothing_found(monkeypatch):
    seen_tool_results = []

    def fake_create(**kwargs):
        # Once the tool_result turn comes back, assert on what it said,
        # then end the loop.
        if len(kwargs["messages"]) > 1:
            seen_tool_results.append(kwargs["messages"][-1])
            return _text_response("done")
        return _tool_use_response("a symbol nobody logged")

    monkeypatch.setattr(engine.client.messages, "create", fake_create)
    result = engine._run_tool_loop(
        "test_stage", "system", [{"role": "user", "content": "hi"}],
        lambda query, top_n=5: [], 100,
    )
    assert result == "done"
    tool_result_content = seen_tool_results[0]["content"][0]["content"]
    assert "No matching dreams found" in tool_result_content


def test_run_tool_loop_gives_up_after_max_iterations(monkeypatch):
    monkeypatch.setattr(
        engine.client.messages, "create",
        lambda **kwargs: _tool_use_response("keep searching forever"),
    )
    search_calls = []
    result = engine._run_tool_loop(
        "test_stage", "system", [{"role": "user", "content": "hi"}],
        lambda query, top_n=5: search_calls.append(1) or [], 100,
    )
    assert result == ""
    assert len(search_calls) == engine.MAX_TOOL_LOOP_ITERATIONS


def test_run_tool_loop_search_fn_none_tool_call_gets_empty_result(monkeypatch):
    # No search_fn wired up at all (e.g. a caller that doesn't have
    # per-user retrieval available) -- the tool call should still
    # resolve cleanly, just with nothing found, rather than crashing.
    calls = iter([
        _tool_use_response("anything"),
        _text_response("answered anyway"),
    ])
    monkeypatch.setattr(engine.client.messages, "create", lambda **kwargs: next(calls))
    result = engine._run_tool_loop("test_stage", "system", [{"role": "user", "content": "hi"}], None, 100)
    assert result == "answered anyway"


def test_run_tool_loop_search_fn_exception_does_not_crash(monkeypatch):
    calls = iter([
        _tool_use_response("anything"),
        _text_response("recovered"),
    ])
    monkeypatch.setattr(engine.client.messages, "create", lambda **kwargs: next(calls))

    def broken_search(query, top_n=5):
        raise RuntimeError("Pinecone is down")

    result = engine._run_tool_loop("test_stage", "system", [{"role": "user", "content": "hi"}], broken_search, 100)
    assert result == "recovered"


# --- analyze_patterns: doesn't dump full dream text/follow-ups upfront ------

def test_analyze_patterns_too_few_dreams_short_circuits():
    # Should return its "come back later" message without ever touching
    # Claude -- confirmed here by not monkeypatching the client at all;
    # a real call would fail loudly (no network in tests) if this didn't
    # short-circuit.
    result = engine.analyze_patterns([{"timestamp": "2026-01-01T00:00:00", "symbols": [], "emotions": [], "themes": []}])
    assert "A few more dreams" in result


def test_analyze_patterns_prompt_omits_raw_text_and_followups(monkeypatch):
    # The whole point of Phase 5's rework: the model gets a lightweight
    # index (dates + tags) up front, and has to call search_dreams to see
    # a dream's actual text or follow-up conversation -- neither should
    # be sitting in the initial prompt where the model could "see" them
    # without a tool call.
    captured = {}

    def fake_loop(stage, system, messages, search_fn, max_tokens):
        captured["prompt"] = messages[0]["content"]
        return "a reading"

    monkeypatch.setattr(engine, "_run_tool_loop", fake_loop)
    all_dreams = [
        {
            "timestamp": f"2026-01-0{i}T00:00:00", "symbols": ["water"],
            "emotions": ["calm"], "themes": ["renewal"],
            "raw_text": "SECRET RAW TEXT THAT SHOULD NOT BE IN THE INDEX",
            "conversation": [{"role": "user", "content": "SECRET FOLLOWUP THAT SHOULD NOT BE IN THE INDEX"}],
        }
        for i in range(1, 4)
    ]
    result = engine.analyze_patterns(all_dreams)
    assert result == "a reading"
    assert "SECRET RAW TEXT" not in captured["prompt"]
    assert "SECRET FOLLOWUP" not in captured["prompt"]
    assert "water" in captured["prompt"]  # the tag vocabulary is still there


# --- extract_dream_data: icon sanitization -----------------------------------

def test_extract_dream_data_keeps_only_recognized_icon_categories(monkeypatch):
    # A real symbol/theme classification call, with one valid category
    # ("door"), one the model made up that isn't in ICON_CATEGORIES
    # ("spaceship"), and one explicit null (nothing fits) -- only the
    # valid one should survive into symbol_icons.
    raw = (
        '{"symbols": ["a door", "a strange console", "a feeling"], '
        '"emotions": [], "people": [], "settings": [], "themes": [], '
        '"symbol_icons": {"a door": "door", "a strange console": "spaceship", "a feeling": null}}'
    )
    monkeypatch.setattr(engine.client.messages, "create", lambda **kwargs: _text_response(raw))
    result = engine.extract_dream_data("I walked through a door.")
    assert result["symbol_icons"] == {"a door": "door"}


def test_extract_dream_data_missing_symbol_icons_defaults_to_empty(monkeypatch):
    raw = '{"symbols": ["a door"], "emotions": [], "people": [], "settings": [], "themes": []}'
    monkeypatch.setattr(engine.client.messages, "create", lambda **kwargs: _text_response(raw))
    result = engine.extract_dream_data("I walked through a door.")
    assert result["symbol_icons"] == {}
