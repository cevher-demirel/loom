"""
tests/test_engine.py -- unit tests for the parts of engine.py that don't
call Claude or Voyage: cosine similarity math, JSON-parsing fallback,
and the similarity-filtering logic. No API key needed to run this file
and no network call happens -- these are pure functions.
"""

import math

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
