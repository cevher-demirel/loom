#!/usr/bin/env python3
"""Run the Stage 30 migration on a COPY of a SQLite backup, entirely on your own computer.

    python scripts/migrate_copy_check.py --db "D:\\path\\to\\backup.db"       (mount your encrypted container first)

* The original file(s) are only READ (copied into a temporary folder, together with a sibling -wal/-shm file
  if present); their SHA-256 is compared before and after to prove nothing changed.
* The copy is checked (integrity_check), migrated with this repository's init_db() three times, and compared
  table by table (row count + hash of every row) before/after. Existing tables must be byte-identical.
* It prints ONLY table names, counts, hashes and yes/no results: never emails, names, dream text or tokens.
* The temporary copy is deleted at the end. Nothing is sent anywhere. No network, no Turso (the Turso variables
  are cleared before the app code is loaded).
Exit: 0 pass, 1 problem found, 2 usage.
"""
import argparse, hashlib, os, shutil, sqlite3, sys, tempfile
from pathlib import Path

for k in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "PINECONE_API_KEY", "RESEND_API_KEY"):
    os.environ[k] = ""                              # must happen before `import database`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True)
a = ap.parse_args()
src = Path(a.db)
if not src.is_file():
    print(f"No such file: {src}", file=sys.stderr); sys.exit(2)
parts = [src] + [p for p in (Path(str(src) + "-wal"), Path(str(src) + "-shm")) if p.is_file()]
def digest(paths):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
orig_before = digest(parts)

# Keep EVERYTHING (the working copy and any SQLite spill files) in the same folder/volume as
# the source, so a copy of a backup on an encrypted drive never lands in the system temp folder.
tmp = Path(tempfile.mkdtemp(prefix="loom_copy_check_", dir=str(src.resolve().parent)))
for _v in ("TMP", "TEMP", "TMPDIR", "SQLITE_TMPDIR"):
    os.environ[_v] = str(tmp)
tempfile.tempdir = str(tmp)
try:
    work = tmp / "copy.db"
    shutil.copy2(src, work)
    for suffix in ("-wal", "-shm"):
        s = Path(str(src) + suffix)
        if s.is_file():
            shutil.copy2(s, str(work) + suffix)
    import database as db
    db.USE_TURSO = False; db.DB_PATH = str(work)

    def snapshot():
        out = {}
        for (t,) in db._execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")[0]:
            rows = db._execute(f'SELECT * FROM "{t}" ORDER BY rowid')[0]
            h = hashlib.sha256()
            for r in rows:
                h.update(repr(tuple(r)).encode()); h.update(b"\n")
            out[t] = (len(rows), h.hexdigest(), [c[1] for c in db._execute(f'PRAGMA table_info("{t}")')[0]])
        return out

    problems = []
    ic = db._execute("PRAGMA integrity_check")[0][0][0]
    print(f"integrity_check on the copy: {ic}")
    if ic != "ok": problems.append("integrity_check not ok")
    before = snapshot()
    print("tables before:", {t: v[0] for t, v in before.items()})
    users = before.get("users", (0,))[0]; dreams = before.get("dreams", (0,))[0]
    if "users" in before:
        n_case = db._execute("SELECT COUNT(*) FROM users WHERE email IS NOT NULL AND email != '' AND email != LOWER(email)")[0][0][0]
        n_blank = db._execute("SELECT COUNT(*) FROM users WHERE email IS NULL OR email = ''")[0][0][0]
        n_dupe = db._execute("SELECT COUNT(*) FROM (SELECT LOWER(email) e FROM users WHERE email != '' GROUP BY LOWER(email) HAVING COUNT(*) > 1)")[0][0][0]
        print(f"users with a mixed-case email: {n_case} | users without an email: {n_blank} | emails shared by several accounts: {n_dupe}")
    snaps = []
    for _ in range(3):
        db.init_db(); snaps.append(snapshot())
    after = snaps[0]
    changed = [t for t, v in before.items() if t not in after or after[t] != v]
    print("existing tables unchanged by migration:", not changed, changed if changed else "")
    print("new tables:", sorted(set(after) - set(before)), {t: after[t][0] for t in sorted(set(after) - set(before))})
    print("repeat runs change nothing:", all(s == after for s in snaps[1:]))
    if changed: problems.append("existing tables changed")
    if not all(s == after for s in snaps[1:]): problems.append("migration not repeatable")
    if "auth_identities" in after:
        c = db.auth_identity_conflicts()
        print("identity conflicts:", {k: v for k, v in c.items() if "dup" in k or "orphan" in k})
    print(f"accounts: {users} -> {after.get('users', (0,))[0]} | dreams: {dreams} -> {after.get('dreams', (0,))[0]}")
    if (users, dreams) != (after.get("users", (0,))[0], after.get("dreams", (0,))[0]): problems.append("counts changed")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
orig_after = digest(parts)
print("original backup file(s) unchanged:", orig_before == orig_after)
if orig_before != orig_after: problems.append("ORIGINAL CHANGED")
print("temporary copy removed:", not tmp.exists())
print("RESULT:", "PASS" if not problems else "PROBLEMS: " + "; ".join(problems))
sys.exit(1 if problems else 0)
