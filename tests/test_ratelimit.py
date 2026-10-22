"""
tests/test_ratelimit.py -- unit tests for ratelimit.py, kept separate
from test_main.py since these exercise the module's own functions
directly rather than going through a live endpoint.
"""

import ratelimit


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    """Just enough of a Request to exercise client_ip() -- a headers
    dict (case-insensitive lookup isn't needed here since the code only
    ever reads the one lowercase key it itself sets) and a .client with
    a .host, matching what request.headers.get(...) and
    request.client.host actually look like on a real FastAPI Request."""
    def __init__(self, headers=None, host="10.0.0.5"):
        self.headers = headers or {}
        self.client = _FakeClient(host) if host is not None else None


def test_client_ip_falls_back_to_request_client_host_with_no_header():
    # No proxy in front at all (e.g. local dev) -- the raw peer address
    # is all there is, so that's what this should return.
    req = _FakeRequest(headers={}, host="127.0.0.1")
    assert ratelimit.client_ip(req) == "127.0.0.1"


def test_client_ip_trusts_the_last_forwarded_entry_not_the_first():
    # Render appends to whatever X-Forwarded-For the caller already
    # sent rather than replacing it -- so the first entry is fully
    # attacker-controlled (trusting it would let anyone claim to be any
    # IP), while the last entry is the one Render's own edge appended
    # from the real TCP connection. See ratelimit.client_ip's own
    # docstring for the full reasoning.
    req = _FakeRequest(headers={"x-forwarded-for": "1.2.3.4, 203.0.113.9"})
    assert ratelimit.client_ip(req) == "203.0.113.9"


def test_client_ip_handles_a_single_forwarded_entry():
    req = _FakeRequest(headers={"x-forwarded-for": "203.0.113.9"})
    assert ratelimit.client_ip(req) == "203.0.113.9"


def test_client_ip_strips_whitespace_around_entries():
    req = _FakeRequest(headers={"x-forwarded-for": "1.2.3.4,   203.0.113.9  "})
    assert ratelimit.client_ip(req) == "203.0.113.9"


def test_client_ip_falls_back_when_header_is_present_but_empty():
    req = _FakeRequest(headers={"x-forwarded-for": ""}, host="127.0.0.1")
    assert ratelimit.client_ip(req) == "127.0.0.1"


def test_client_ip_is_unknown_with_no_header_and_no_client():
    req = _FakeRequest(headers={}, host=None)
    assert ratelimit.client_ip(req) == "unknown"


def test_allow_blocks_after_max_calls_within_window():
    ratelimit.reset()
    for _ in range(3):
        assert ratelimit.allow("k", max_calls=3, window_seconds=60) is True
    assert ratelimit.allow("k", max_calls=3, window_seconds=60) is False


def test_allow_keys_are_independent():
    ratelimit.reset()
    for _ in range(3):
        assert ratelimit.allow("a", max_calls=3, window_seconds=60) is True
    # A different key has its own, untouched budget.
    assert ratelimit.allow("b", max_calls=3, window_seconds=60) is True
