#!/usr/bin/env python3
"""READ-ONLY row counts and schema fingerprint, for verifying a database backup. Prints NO user content:
table names, row counts and one SHA-256 of the schema text only.

    python scripts/db_counts.py --db path/to/copy.db                 > counts-copy.txt
    python scripts/db_counts.py --configured-backend --i-am-the-operator > counts-prod.txt   (operator's own shell)
    python scripts/db_counts.py --compare counts-prod.txt counts-backup.txt

--compare reads two saved outputs (no database access). Exit 0 = identical, 1 = differ, 2 = usage/refused.
Never runs migrations (does not call init_db); only SELECT statements can reach the database.
"""
import argparse, hashlib, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ap = argparse.ArgumentParser()
ap.add_argument("--db"); ap.add_argument("--configured-backend", action="store_true")
ap.add_argument("--i-am-the-operator", action="store_true"); ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
a = ap.parse_args()

if a.compare:
    def load(p):
        return {l.split(":")[0].strip(): l.split(":", 1)[1].strip() for l in Path(p).read_text().splitlines() if ":" in l and not l.startswith("#")}
    x, y = load(a.compare[0]), load(a.compare[1])
    diff = [k for k in sorted(set(x) | set(y)) if x.get(k) != y.get(k)]
    for k in diff:
        print(f"DIFFERENT {k}: {x.get(k, '<missing>')} vs {y.get(k, '<missing>')}")
    print("RESULT: identical" if not diff else f"RESULT: {len(diff)} difference(s)")
    sys.exit(1 if diff else 0)

if bool(a.db) == bool(a.configured_backend):
    print("Choose exactly one of --db, --configured-backend (or use --compare).", file=sys.stderr); sys.exit(2)
if a.configured_backend and not a.i_am_the_operator:
    print("Refusing to touch the configured backend without --i-am-the-operator.", file=sys.stderr); sys.exit(2)
if a.db:
    if not Path(a.db).is_file():
        print(f"No such file: {a.db}", file=sys.stderr); sys.exit(2)
    for k in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"):
        os.environ[k] = ""
import database  # noqa: E402
if a.db:
    database.USE_TURSO = False; database.DB_PATH = a.db
_real = database._execute
def _read_only(sql, params=()):
    if sql.lstrip().split(None, 1)[0].upper() != "SELECT":
        raise RuntimeError("db_counts is read-only; refused a non-SELECT statement")
    return _real(sql, params)
database._execute = _read_only

tables = [r[0] for r in database._execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")[0]]
schema = "\n".join(str(r[0]) for r in database._execute(
    "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name")[0])
print("# row counts and schema fingerprint only; no user content")
print(f"schema_sha256: {hashlib.sha256(schema.encode()).hexdigest()}")
for t in tables:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", t):
        print(f"skipped_unusual_table_name: 1"); continue
    print(f"{t}: {database._execute(f'SELECT COUNT(*) FROM {t}')[0][0][0]}")
