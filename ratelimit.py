"""
ratelimit.py -- a small in-memory, per-key rate limiter for the handful
of endpoints an anonymous caller can hit without a login token first:
/signup, /login, /forgot-password, /resend-verification. Those are
exactly the ones that either try a password or send an email, so with
no limit at all, a caller could brute-force a login or spam someone
else's inbox with reset/verification emails just by hitting the
endpoint in a loop -- at zero cost to themselves and (for the email
ones) real cost against Resend's sending quota.

Deliberately in-memory rather than Redis- or database-backed: Loom runs
as a single process today, so a dict guarded by a lock is enough to
actually stop that abuse, and it adds no new infrastructure or
dependency. The trade-off worth knowing: counts reset on every process
restart, and don't share across multiple instances if this is ever
horizontally scaled -- revisit then, not before.
"""

import threading
import time
from collections import defaultdict, deque

_lock = threading.Lock()
_hits = defaultdict(deque)


def allow(key, max_calls, window_seconds):
    """
    True if this call should proceed, False if `key` has already made
    `max_calls` calls within the trailing `window_seconds`. Only records
    a call when it's allowed -- a caller already over the limit doesn't
    get to keep pushing their own window forward just by retrying faster,
    they simply stay blocked until an earlier allowed call ages out.
    """
    now = time.monotonic()
    with _lock:
        hits = _hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= max_calls:
            return False
        hits.append(now)
        return True


def reset():
    """
    Wipe every tracked count. Not used by the running app at all -- it
    exists for tests/conftest.py, so that one test hammering /signup or
    /login doesn't leave the next test starting out already partway (or
    all the way) through its limit, just because both share this same
    in-process module.
    """
    with _lock:
        _hits.clear()


def client_ip(request):
    """
    Best-effort caller IP for rate-limiting purposes. Uses the raw TCP
    peer address (request.client.host) rather than trusting an
    X-Forwarded-For header, since that header is just a string the
    caller can set to anything -- fine behind no proxy, but if this ever
    sits behind one (nginx, a load balancer, Render/Fly's own edge),
    switch this to read the proxy's *own* trusted forwarded-for value,
    not the raw header, or every caller can claim to be a different IP
    and this whole module stops doing anything.
    """
    return request.client.host if request.client else "unknown"
