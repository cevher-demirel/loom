"""
tests/conftest.py -- shared pytest fixtures and test isolation setup.

The most important job of this file is making sure the test suite can
NEVER touch anything real: a real Turso database, a real Pinecone
index, or your actual local loom.db with your own logged dreams in it.
database.py and vectorstore.py both read their configuration from
os.environ the moment they're imported (not when a function is called),
and main.py calls database.init_db() as soon as it's imported too -- so
all of this has to happen at the top of this file, before any test
module does "import main" or "import database", not inside a fixture
(fixtures only run once a test actually starts, which is already too
late).
"""

import os

# Force every test to run against local SQLite, never a real Turso
# database, and with Pinecone treated as "not configured" -- regardless
# of what's sitting in .env on whatever machine runs this suite.
#
# Set to "" rather than popped: database.py and vectorstore.py both call
# python-dotenv's load_dotenv() at import time, and load_dotenv() only
# fills in variables that are completely ABSENT from os.environ -- it
# never overwrites one that's already set, even to an empty string. Pop
# these instead of setting them empty and load_dotenv() would just load
# the real values straight back out of .env a moment later, silently
# undoing this.
os.environ["TURSO_DATABASE_URL"] = ""
os.environ["TURSO_AUTH_TOKEN"] = ""
os.environ["PINECONE_API_KEY"] = ""
# Stage 7 audit finding: emailer.py reads RESEND_API_KEY at import time
# the same way database.py/vectorstore.py read their own credentials,
# but this file never blanked it. In an environment where that key IS
# set (unlike this container's own .env, where it happens not to be),
# running the suite's password-recovery tests would silently fire real
# HTTPS calls to Resend's API for every /forgot-password test -- not a
# production DATABASE write, but exactly the kind of uncontrolled
# external side effect this file exists to rule out. Blank it for the
# same reason and the same way as the three above.
os.environ["RESEND_API_KEY"] = ""
# The Google sign-in tests written before the owner-only switch exercise the *public* behaviour,
# so the suite defaults to it; tests/test_google_owner_mode.py overrides this per test to prove
# the restricted (default-on-a-real-server) mode. A real .env must never leak a key or list in.
os.environ["GOOGLE_SIGNIN_MODE"] = "public"
os.environ["GOOGLE_TEST_KEY"] = ""
os.environ["GOOGLE_TEST_EMAILS"] = ""

import tempfile

import pytest

import devsafety
import database
import ratelimit

# Self-check: confirm the blanking above actually took effect, in the
# same process, before any test runs. This doesn't add any new
# behavior on its own -- devsafety.assert_isolated_environment() only
# raises if one of the four guarded variables is still non-empty -- but
# it means a future edit to this file that accidentally removes or
# reorders one of the blanking lines above fails loudly here, rather
# than silently letting a real credential through to whatever test
# runs first.
devsafety.assert_isolated_environment()


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    """
    ratelimit.py tracks call counts in a module-level dict, which (unlike
    the database) isn't something any per-test fixture already resets --
    it has no concept of "per test" at all, just whatever's accumulated
    in this process. Autouse so every test starts with a clean slate
    regardless of whether it explicitly asked for one; otherwise test
    order would start to matter; e.g. enough earlier tests calling
    /signup would make a later, unrelated test start failing with 429s
    purely because it happened to run after them.
    """
    ratelimit.reset()
    yield

# Whatever module first does "import main" also triggers main's
# module-level database.init_db() call, before any fixture below has
# had a chance to redirect DB_PATH -- point it at a throwaway temp file
# from the very start so that initial call can't create a loom.db (or
# touch a real one) sitting in whatever directory pytest happens to run
# from.
_import_time_fd, _import_time_db_path = tempfile.mkstemp(suffix=".db", prefix="loom_test_import_")
os.close(_import_time_fd)
database.DB_PATH = _import_time_db_path
database.USE_TURSO = False


# Optional: run the same tests through the Turso code path (libsql_client) against a
# libSQL server on THIS machine. Opt-in, and hard-limited to a local address so it can
# never reach Turso: set LOOM_LIBSQL_TEST_URL=http://127.0.0.1:<port>  (see
# docs/stage30/TURSO_PATH_REHEARSAL.md). Not used by default or by CI.
_LIBSQL_TEST_URL = os.environ.get("LOOM_LIBSQL_TEST_URL", "")
if _LIBSQL_TEST_URL:
    from urllib.parse import urlparse as _urlparse
    if _urlparse(_LIBSQL_TEST_URL).hostname not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError("LOOM_LIBSQL_TEST_URL must be a local address (127.0.0.1/localhost); refusing")
_libsql_client = None


def _libsql():
    global _libsql_client
    if _libsql_client is None:
        import libsql_client
        _libsql_client = libsql_client.create_client_sync(url=_LIBSQL_TEST_URL)
    return _libsql_client


def pytest_sessionfinish(session, exitstatus):
    # libsql_client keeps a background thread; close it or the process cannot exit.
    if _libsql_client is not None:
        try:
            _libsql_client.close()
        except Exception:
            pass


def sqlite_only(reason="inspects the SQLite file directly"):
    """Mark a test that only makes sense on the local SQLite file (skipped in libSQL mode)."""
    return pytest.mark.skipif(bool(_LIBSQL_TEST_URL), reason=reason)


@pytest.fixture
def fresh_db(monkeypatch):
    """
    A brand-new, empty local SQLite database for one test, deleted
    afterward. Use this on any test that touches database.py or calls
    an endpoint that does (which is most of tests/test_main.py) --
    without it, tests would share state through whatever
    database.DB_PATH currently points at, and tests would start
    affecting each other's results depending on run order.
    """
    if _LIBSQL_TEST_URL:
        client = _libsql()
        for (name,) in client.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").rows:
            client.execute(f'DROP TABLE "{name}"')
        monkeypatch.setattr(database, "_client", client, raising=False)
        monkeypatch.setattr(database, "USE_TURSO", True)
        database.init_db()
        yield
        return
    fd, path = tempfile.mkstemp(suffix=".db", prefix="loom_test_")
    os.close(fd)
    monkeypatch.setattr(database, "DB_PATH", path)
    monkeypatch.setattr(database, "USE_TURSO", False)
    database.init_db()
    yield
    try:
        os.unlink(path)
    except OSError:
        pass
