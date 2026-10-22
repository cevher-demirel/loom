"""
ratelimit.py -- a small in-memory, per-key rate limiter for the handful
of endpoints an anonymous caller can hit without a login token first:
/signup, /login, /forgot-password, /resend-verification. Those are
exactly the ones that either try a password or send an email, so with
no limit at all, a caller could brute-force a login or spam someone
else's inbox with reset/verification emails just by hitting the
endpoint in a loop -- at zero cost to themselves and (for the email
ones) real cost against Resend's sending quota.

Deliberately in-memory rather than Redis- or database-backed: Loominous runs
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
    Best-effort caller IP for rate-limiting purposes.

    Loominous runs behind Render's edge proxy in production, so
    request.client.host isn't the caller's real address -- it's
    whichever internal address Render's proxy connects from, which is
    the same for every request. Used alone, that collapses every rate
    limit in this file onto one shared key: one person maxing out
    /login's attempt limit would lock out everyone else trying to log
    in at the same time, and the signup/forgot-password limits would be
    similarly meaningless (shared across all callers, not actually
    per-caller). Render does set X-Forwarded-For, but it *appends* to
    whatever the header already held rather than replacing it -- Render
    doesn't strip what an inbound caller sent first, so the header can
    look like "<anything the caller claims>, <the IP Render's edge
    actually saw>". Trusting the first entry would mean trusting a
    value the caller fully controls, which defeats the point. The last
    entry is the one Render's own edge appended from the real TCP
    connection, so that's the one entry here that isn't just whatever
    the caller felt like sending -- this takes that one, the standard
    "trust exactly one upstream proxy" pattern. (If another proxy, e.g.
    a CDN, is ever added in front of Render, this needs to peel one more
    hop -- the second-to-last entry, not the last.)
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"
