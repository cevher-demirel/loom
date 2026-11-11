#!/usr/bin/env python3
"""Stage 30 migration rehearsal on a SEPARATE libSQL/Turso database with SYNTHETIC data.

It never reads or needs production data. Steps (each in its own process, like a real deploy):
  1. seed     -- OLD production code (commit 166ac63's database.py) builds the old schema and
                 65 synthetic accounts / 183 synthetic dreams / profiles
  2. snapshot -- per-table row counts + SHA-256 of every row (prints hashes and counts, never content)
  3. migrate  -- NEW code's init_db(), run repeatedly (a restart is a re-run)
  4. snapshot again and compare: every pre-existing table must be byte-identical
  5. app      -- old accounts still sign in (through the real /login route); /dreams counts match;
                 Google identity create/link on the migrated data; unrelated identity cannot take an account

Usage:  python scripts/migration_rehearsal.py --url http://127.0.0.1:8098
Allowed targets: this machine (127.0.0.1/localhost) or a Turso database whose name starts with
"loom-rehearsal" (set TURSO_AUTH_TOKEN in YOUR shell for that; also pass --allow-remote-scratch).
The production database is named "loom" and is refused. The OLD code comes from `git show 166ac63:database.py`.
"""
import argparse, hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OLD_COMMIT = "166ac63"
PASSWORD = "Rehearsal-Pass-1!"          # synthetic, for synthetic accounts only
N_USERS, N_DREAMS = 65, 183


def check_target(url, allow_remote):
    host = (urlparse(url).hostname or "").lower()
    if host in ("127.0.0.1", "localhost", "::1"):
        return
    if allow_remote and host.startswith("loom-rehearsal"):
        return
    sys.exit(f"REFUSED: {host or url!r} is not this machine or a 'loom-rehearsal*' scratch database. "
             "Production ('loom') is never allowed.")


def child(role, url, extra_path=None):
    env = dict(os.environ)
    env.update({"TURSO_DATABASE_URL": url, "PINECONE_API_KEY": "", "RESEND_API_KEY": "",
                "ANTHROPIC_API_KEY": env.get("ANTHROPIC_API_KEY", "x-placeholder"),
                "VOYAGE_API_KEY": env.get("VOYAGE_API_KEY", "x-placeholder"), "PYTHONDONTWRITEBYTECODE": "1"})
    if not url.startswith(("http://127.0.0.1", "http://localhost")):
        env.setdefault("TURSO_AUTH_TOKEN", "")
    else:
        env["TURSO_AUTH_TOKEN"] = ""
    env["PYTHONPATH"] = (extra_path or str(ROOT))
    r = subprocess.run([sys.executable, "-I" if False else "-u", str(Path(__file__).resolve()), "--role", role, "--url", url],
                       env=env, capture_output=True, text=True, cwd=extra_path or str(ROOT))
    if r.returncode != 0:
        print(r.stdout[-2000:]); print(r.stderr[-2000:], file=sys.stderr)
        sys.exit(f"step '{role}' failed")
    return r.stdout


# ---------------- roles executed inside child processes ----------------
def role_seed():
    import database as db                       # the OLD module (PYTHONPATH points at the old code)
    assert db.USE_TURSO, "old code did not pick up the Turso URL"
    db.init_db()
    ids = []
    for i in range(N_USERS):
        email = f"synthetic{i:03d}@example.test" if i % 5 else None
        ids.append(db.create_user(f"synthetic_user_{i:03d}", email or "", PASSWORD)["id"])
    for n in range(N_DREAMS):
        uid = ids[n % N_USERS]
        ext = {"symbols": ["synthetic-symbol-%d" % (n % 9)], "emotions": ["calm"], "people": [], "settings": ["synthetic place"], "themes": ["synthetic"]}
        db.insert_dream(uid, f"Synthetic dream number {n}.", ext, f"Synthetic interpretation {n}.", [0.0, 1.0],
                        timestamp=f"2026-0{1 + n % 9}-1{n % 9}T08:00:00")
    for uid in ids[:40]:
        db.save_profile(uid, {"name": f"Synthetic {uid}", "bio": "synthetic profile"})
    print(json.dumps({"users": len(ids), "dreams": N_DREAMS}))


def role_snapshot():
    import database as db
    out = {}
    tables = [r[0] for r in db._execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")[0]]
    for t in tables:
        rows = db._execute(f'SELECT * FROM "{t}" ORDER BY rowid')[0]
        h = hashlib.sha256()
        for r in rows:
            h.update(repr(tuple(r)).encode()); h.update(b"\n")
        cols = [c[1] for c in db._execute(f'PRAGMA table_info("{t}")')[0]]
        out[t] = {"rows": len(rows), "sha256": h.hexdigest(), "columns": cols}
    print(json.dumps(out))


def role_migrate():
    import database as db
    assert db.USE_TURSO
    db.init_db()
    print("ok")


def role_app():
    os.environ.setdefault("ANTHROPIC_API_KEY", "x-placeholder")
    import database as db, ratelimit
    from fastapi.testclient import TestClient
    import main
    c = TestClient(main.app)
    ok = 0
    for i in range(N_USERS):                                      # every old account still authenticates
        u = db.authenticate_user(f"synthetic_user_{i:03d}", PASSWORD)
        ok += bool(u)
    assert ok == N_USERS, f"only {ok}/{N_USERS} old accounts authenticate"
    assert db.authenticate_user("synthetic_user_000", "wrong-password") is None
    sampled, dreams_seen = 0, 0
    for i in range(0, N_USERS, 7):                               # real /login + /dreams route on a sample
        ratelimit.reset()
        r = c.post("/login", json={"username": f"synthetic_user_{i:03d}", "password": PASSWORD})
        assert r.status_code == 200, r.status_code
        d = c.get("/dreams", headers={"Authorization": "Bearer " + r.json()["token"]})
        assert d.status_code == 200
        expected = len([n for n in range(N_DREAMS) if n % N_USERS == i])
        assert len(d.json()) == expected, f"user {i}: {len(d.json())} dreams, expected {expected}"
        sampled += 1; dreams_seen += expected
    # Google identity on migrated data
    uid = db.find_user_by_email("synthetic001@example.test")["id"]
    assert db.link_identity_safely(uid, "google", "rehearsal-sub-1", "synthetic001@example.test") == "linked"
    assert db.link_identity_safely(uid, "google", "rehearsal-sub-1", "synthetic001@example.test") == "already"
    assert db.find_identity("google", "rehearsal-sub-1")["user_id"] == uid
    other = db.find_user_by_email("synthetic002@example.test")["id"]
    assert db.link_identity_safely(other, "google", "rehearsal-sub-1", "x@example.test") == "conflict", "identity attached to a second account"
    assert db.link_identity_safely(uid, "google", "rehearsal-sub-2", "x@example.test") == "conflict", "second identity attached to same account"
    assert db.find_identity("google", "rehearsal-sub-2") is None and db.find_user_identity(other, "google") is None
    new_id = db.create_user_from_identity("google", "rehearsal-sub-3", "newperson@example.test", "newperson")
    assert db.find_identity("google", "rehearsal-sub-3")["user_id"] == new_id
    print(json.dumps({"accounts_authenticated": ok, "sampled_logins": sampled, "sampled_dreams_matched": dreams_seen}))


def main_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True); ap.add_argument("--role"); ap.add_argument("--allow-remote-scratch", action="store_true")
    a = ap.parse_args()
    check_target(a.url, a.allow_remote_scratch)
    if a.role:
        try:
            globals()["role_" + a.role]()
            code = 0
        except BaseException:
            import traceback; traceback.print_exc(); code = 1
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(code)       # libsql_client keeps a non-daemon thread; always exit explicitly
    old = Path(tempfile.mkdtemp(prefix="loom_old_code_"))
    (old / "database.py").write_text(subprocess.run(["git", "show", f"{OLD_COMMIT}:database.py"], cwd=ROOT, capture_output=True, text=True, check=True).stdout)
    print("1. seeding with OLD production code ...", child("seed", a.url, str(old)).strip())
    before = json.loads(child("snapshot", a.url))
    print("2. snapshot before:", {t: v["rows"] for t, v in before.items()})
    runs = []
    for n in (1, 2, 3):
        child("migrate", a.url); runs.append(json.loads(child("snapshot", a.url)))
    after = runs[0]
    print("3. migrated with NEW code 3 times (a restart is a re-run)")
    bad = []
    for t, v in before.items():
        if t not in after: bad.append(f"table {t} disappeared")
        elif v["sha256"] != after[t]["sha256"] or v["rows"] != after[t]["rows"]: bad.append(f"table {t} changed")
        elif v["columns"] != after[t]["columns"]: bad.append(f"table {t} columns changed")
    new_tables = sorted(set(after) - set(before))
    print("4. pre-existing tables identical:", not bad, "| new tables:", new_tables, "| new-table rows:", {t: after[t]["rows"] for t in new_tables})
    repeat_ok = all(r == after for r in runs[1:])
    print("   repeat runs change nothing:", repeat_ok)
    print("5. app checks:", child("app", a.url).strip())
    final = json.loads(child("snapshot", a.url))
    print("   users now:", final["users"]["rows"], "(65 + 1 Google sign-up); dreams:", final["dreams"]["rows"])
    ok = not bad and repeat_ok and final["dreams"]["rows"] == N_DREAMS and final["users"]["rows"] == N_USERS + 1
    for b in bad: print("PROBLEM:", b)
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main_cli()
