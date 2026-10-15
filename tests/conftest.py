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

import tempfile

import pytest

import database

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
