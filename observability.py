"""
observability.py -- Phase 3 of Loominous's engineering roadmap: structured
logging and latency tracing.

Why this exists: before this file, Loominous had exactly one logger.warning
call in the whole codebase. If a request was slow, or a Claude call
failed, there was no record of it -- the only way to find out something
had gone wrong was a person telling you. This doesn't change what the
app does (every function behaves exactly the same); it adds a second,
parallel channel that answers "what actually happened on that request"
after the fact, without needing to reproduce the problem or add a print
statement and redeploy.

Log lines are single-line JSON (one event per line) rather than
Python's default free-text format -- that's what makes them queryable.
Render (and most hosts) capture stdout, so these lines show up in the
same log viewer as everything else; the JSON shape just means they can
also be grepped/filtered by field ("show me every request over 5s") or
loaded into a real log tool later without reformatting anything.
"""

import json
import logging
import sys
import time
import uuid
from contextlib import contextmanager

logger = logging.getLogger("loom")
logger.setLevel(logging.INFO)

if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
    # Don't also hand these up to the root logger -- without this, a
    # structured JSON line would print twice if anything upstream (e.g.
    # uvicorn) has its own root-level handler configured.
    logger.propagate = False


def log_event(event, **fields):
    """
    Emit one structured JSON log line. `event` names what happened
    (e.g. "request", "claude_call", "pipeline_stage"); every keyword
    argument becomes a field on that line, alongside a timestamp added
    automatically. Never raises -- a logging failure should never be
    the thing that breaks an actual request.
    """
    try:
        record = {"event": event, "ts": round(time.time(), 3)}
        record.update(fields)
        logger.info(json.dumps(record, default=str))
    except Exception:
        pass


@contextmanager
def timed(event, **fields):
    """
    Time a block of code and log it as one structured event when it
    exits -- whether it succeeded or raised. duration_ms is always
    present; a failure gets ok=False plus the exception's type and
    message attached, so a failed stage shows up in the logs instead of
    silently vanishing, and the exception still propagates normally
    afterward (this only observes, it never swallows an error).

    Usage:
        with timed("pipeline_stage", stage="extract", request_id=rid):
            extracted = engine.extract_dream_data(raw_text)
    """
    start = time.monotonic()
    try:
        yield
    except Exception as exc:
        log_event(event, duration_ms=round((time.monotonic() - start) * 1000, 1),
                  ok=False, error=f"{type(exc).__name__}: {exc}", **fields)
        raise
    else:
        log_event(event, duration_ms=round((time.monotonic() - start) * 1000, 1),
                  ok=True, **fields)


def new_request_id():
    """
    A short id to tie together every log line produced by one HTTP
    request -- the overall request event plus each pipeline stage
    inside it -- so they can be grepped as a group afterward.
    """
    return uuid.uuid4().hex[:12]
