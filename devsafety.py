"""
devsafety.py -- an explicit, opt-in guard against accidentally running
test or ad hoc local code against the real production Turso database,
Pinecone index, or Resend account.

Nothing in this file runs automatically. Production's own startup path
(main.py, database.py, vectorstore.py, emailer.py) does not import this
module and is completely unaffected by its existence -- that is
deliberate. Stage 7's spec explicitly warns against adding a mandatory
ENVIRONMENT=production-style gate to live code unless production
compatibility with that gate can be demonstrated without changing
Render's own configuration, which isn't something this session can
verify. So this stays a tool that test code and any future ad hoc local
script (the same category of script that wrote disposable test records
to production during Stages 1-6) can choose to call on themselves,
rather than a check the live app is forced through.

Why presence-or-absence, not a host-pattern allowlist: an allowlist of
"safe-looking" Turso URL shapes (e.g. a regex for libsql://*-local or
similar) is exactly the kind of brittle check that can misclassify a
real production URL as safe if Turso ever changes its URL format, or
if a production database is ever renamed to something that happens to
match the "looks local" pattern. Checking "is this credential simply
present in the environment at all" has no such failure mode -- it can
be too strict (refusing a value that would have been harmless) but it
can never be fooled into treating a real production credential as
safe.
"""

import os

# Every credential that, if non-empty, means this process could reach
# a real, live, non-free external service: Turso (the production
# database itself), Pinecone (the vector index), and Resend (outbound
# email). Anthropic/Voyage keys are deliberately left out of this list
# -- tests already avoid spending money on those by monkeypatching
# engine.py's functions directly (see tests/test_main.py's mock_engine
# fixture), not by blanking the key, and a key being present doesn't by
# itself risk touching anyone's existing data the way the three below
# do.
GUARDED_ENV_VARS = ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "PINECONE_API_KEY", "RESEND_API_KEY")


class ProductionAccessBlocked(RuntimeError):
    """Raised by assert_isolated_environment() when a credential that
    could reach a real external service is present where isolated
    local/test code expected none."""


def assert_isolated_environment():
    """
    Raise ProductionAccessBlocked if any of GUARDED_ENV_VARS currently
    has a non-empty value in os.environ.

    Call this at the very top of any ad hoc local script, before it
    imports database, vectorstore, or emailer -- the same place
    tests/conftest.py blanks these variables for the whole test
    session (and now also calls this function right after, as a
    self-check that the blanking actually took effect).
    """
    present = [name for name in GUARDED_ENV_VARS if os.environ.get(name)]
    if present:
        raise ProductionAccessBlocked(
            "Refusing to proceed: " + ", ".join(present) + " "
            + ("is" if len(present) == 1 else "are")
            + " set in this environment. This guard exists specifically to "
            "stop a local script or test run from silently reaching a real "
            "Turso database, Pinecone index, or Resend account -- which is "
            "what happened during earlier stages' ad hoc live-verification "
            "testing. Unset these variables (or run inside pytest, where "
            "tests/conftest.py already blanks them for you) before "
            "proceeding."
        )
