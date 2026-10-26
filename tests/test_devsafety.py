"""
tests/test_devsafety.py -- targeted tests for devsafety.py and for the
test-isolation guarantees conftest.py is supposed to provide.

These are deliberately separate from test_stage7_audit.py: that file
tests application behavior against a disposable database; this file
tests the safety machinery itself -- the thing that's supposed to make
sure no test anywhere in this suite can reach a real external service.
None of these tests make a network call; several of them exist
specifically to prove that no network call was even attempted.
"""

import os

import pytest

import devsafety


def test_guard_raises_when_a_fake_production_like_turso_url_is_present(monkeypatch):
    """
    A deliberately production-shaped (but fake) Turso URL must trip the
    guard -- this is what "fail closed" means here: presence of the
    credential is enough to refuse, with no attempt to connect to it
    first (which would itself be a network call this test must not
    make). Using libsql:// (Turso's real scheme) in the fake value
    specifically checks that the guard doesn't try to be clever about
    URL shape -- it blocks on presence alone, which is also why a URL
    this test invents can't accidentally be mistaken for "looks safe."
    """
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://loom-production-fake-example.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "fake-token-for-this-test-only")
    with pytest.raises(devsafety.ProductionAccessBlocked):
        devsafety.assert_isolated_environment()


def test_guard_raises_for_pinecone_key_alone(monkeypatch):
    monkeypatch.setenv("PINECONE_API_KEY", "fake-pinecone-key-for-this-test-only")
    with pytest.raises(devsafety.ProductionAccessBlocked):
        devsafety.assert_isolated_environment()


def test_guard_raises_for_resend_key_alone(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "fake-resend-key-for-this-test-only")
    with pytest.raises(devsafety.ProductionAccessBlocked):
        devsafety.assert_isolated_environment()


def test_guard_passes_when_all_four_are_blank(monkeypatch):
    """This is the state conftest.py puts the real test session in --
    confirm the guard agrees that state is safe, i.e. it isn't
    over-firing on an isolated configuration."""
    for name in devsafety.GUARDED_ENV_VARS:
        monkeypatch.setenv(name, "")
    devsafety.assert_isolated_environment()  # must not raise


def test_current_test_session_is_actually_isolated():
    """
    The real, non-monkeypatched check: by the time this test runs,
    conftest.py has already blanked all four guarded variables for the
    whole session (and already called this exact function once at
    import time). Confirm that state is still true mid-suite -- i.e.
    nothing between here and session start quietly set one of them back
    to a real value.
    """
    for name in devsafety.GUARDED_ENV_VARS:
        assert os.environ.get(name, "") == "", f"{name} is non-empty mid test session"
    devsafety.assert_isolated_environment()  # must not raise


def test_database_module_is_not_using_turso_in_this_test_session():
    """
    Belt-and-suspenders beyond the env-var check: confirm the actual
    runtime state of database.py matches "isolated." conftest.py also
    forces USE_TURSO = False directly (in case a module already cached
    TURSO_URL as truthy before the env var was blanked), so check that
    directly rather than only inferring it from the environment.
    """
    import database
    assert database.USE_TURSO is False


def test_vectorstore_has_no_real_pinecone_client_in_this_test_session():
    """
    vectorstore.py reads PINECONE_API_KEY at import time and only
    creates a real Pinecone client if that key was non-empty at that
    moment. Since conftest.py blanks it before anything imports
    vectorstore, the module-level client must be None -- confirming no
    test in this suite could have created a live Pinecone connection
    even if it tried.
    """
    import vectorstore
    assert vectorstore._pc is None
    assert vectorstore.is_configured() is False


def test_env_test_example_file_contains_no_real_looking_secrets():
    """
    .env.test.example is meant to be committed and copied by hand; a
    secret accidentally left in it would defeat the whole point. Every
    value after '=' must be empty -- not just "doesn't look like a key
    prefix," since even a short placeholder string invites someone to
    assume it's real.
    """
    path = os.path.join(os.path.dirname(__file__), "..", ".env.test.example")
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            assert "=" in line, f"unexpected non-comment, non-assignment line: {line!r}"
            key, _, value = line.partition("=")
            assert value == "", f"{key} has a non-empty value in the example env file: {line!r}"

