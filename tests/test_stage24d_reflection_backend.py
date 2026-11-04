"""Stage 24d -- backend: failures never echo provider internals, nothing partial is cached, retry works."""
import engine
import database
from tests.test_main import client, mock_engine, _auth_headers  # noqa: F401
from tests.test_stage13_streaming_insight import _setup_one_brother_dream, _stream_result_and_meta, SEP


def _post(user):
    return client.post("/symbols/insight/stream", json={"symbol": "Brother", "category": "person"}, headers=_auth_headers(user["token"]))


def test_provider_error_text_is_never_sent_to_the_browser_and_retry_succeeds(fresh_db, mock_engine, monkeypatch):
    user = _setup_one_brother_dream(monkeypatch)

    def failing(symbol, occurrences, concept_label=None, category="symbol"):
        yield f"{SEP}TEASER{SEP}\nhalf\n"
        raise RuntimeError("anthropic.APIStatusError: 529 overloaded sk-ant-SECRET request_id=req_123")

    monkeypatch.setattr(engine, "symbol_insight_stream", failing)
    _body, meta = _stream_result_and_meta(_post(user))
    assert meta["error"] == "The reflection couldn't be finished."
    assert "SECRET" not in str(meta) and "529" not in str(meta) and "req_123" not in str(meta)
    assert database.get_element_interpretation(user["id"], "person:brother") is None     # nothing partial cached

    def good(symbol, occurrences, concept_label=None, category="symbol"):
        yield (f"{SEP}TEASER{SEP}\nt\n{SEP}GENERAL{SEP}\nA general reading.\n{SEP}JOURNAL{SEP}\nj\n"
               f"{SEP}DIRECTION{SEP}\nWhat does it stir?\n{SEP}END{SEP}")

    monkeypatch.setattr(engine, "symbol_insight_stream", good)
    _body, meta2 = _stream_result_and_meta(_post(user))
    assert "error" not in meta2 and meta2["general"] == "A general reading."
    assert database.get_element_interpretation(user["id"], "person:brother") is not None


def test_request_has_a_bounded_timeout_and_headroom():
    assert engine.SYMBOL_INSIGHT_REQUEST_TIMEOUT_SECONDS <= 90
