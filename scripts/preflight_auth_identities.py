#!/usr/bin/env python3
"""READ-ONLY preflight for the Stage 29 identity constraints. Prints COUNTS only:
no emails, usernames, provider subjects, tokens or dream content.

Run it against a COPY first:
    python scripts/preflight_auth_identities.py --db path/to/copy.db

An authorised operator may later run it against the configured backend
(TURSO_DATABASE_URL / TURSO_AUTH_TOKEN in the operator's own shell):
    python scripts/preflight_auth_identities.py --configured-backend --i-am-the-operator
It issues SELECT statements only; it never runs migrations (it does not call
init_db), never writes, never merges or deletes anything.

Exit status: 0 = safe to deploy, 1 = conflicts to resolve first (see counts), 2 = refused/usage.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ap = argparse.ArgumentParser()
ap.add_argument("--db", help="path to a SQLite database file (a copy)")
ap.add_argument("--configured-backend", action="store_true", help="use the backend configured by the environment")
ap.add_argument("--i-am-the-operator", action="store_true", help="required with --configured-backend")
a = ap.parse_args()
if bool(a.db) == bool(a.configured_backend):
    print("Choose exactly one of --db or --configured-backend.", file=sys.stderr); sys.exit(2)
if a.configured_backend and not a.i_am_the_operator:
    print("Refusing to touch the configured backend without --i-am-the-operator.", file=sys.stderr); sys.exit(2)
if a.db:
    if not Path(a.db).is_file():
        print(f"No such file: {a.db}", file=sys.stderr); sys.exit(2)
    for k in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"):
        os.environ[k] = ""                       # a copy is read locally, never Turso

import database  # noqa: E402  (after the environment decision above)

if a.db:
    database.USE_TURSO = False
    database.DB_PATH = a.db

# Belt and braces: whatever happens below, only reads may reach the database.
_real = database._execute
def _read_only(sql, params=()):
    head = sql.lstrip().split(None, 1)[0].upper()
    if head != "SELECT":
        raise RuntimeError("preflight is read-only; refused a non-SELECT statement")
    return _real(sql, params)
database._execute = _read_only

r = database.auth_identity_conflicts()
for k, v in r.items():
    print(f"{k}: {v}")
bad = r.get("duplicate_user_provider_groups", 0) + r.get("duplicate_provider_subject_groups", 0)
if bad:
    print("\nRESULT: CONFLICTS FOUND. Do not deploy yet. Nothing was changed. See docs/stage30/MIGRATION_SAFETY.md > Remediation.")
    sys.exit(1)
if r.get("orphan_identities_without_user"):
    print("\nRESULT: orphan identity rows exist (harmless: ignored by sign-in), review before cleanup.")
print("\nRESULT: no uniqueness conflicts." if r.get("auth_identities_table") else "\nRESULT: no auth_identities table yet; migration will create it empty.")
sys.exit(0)
