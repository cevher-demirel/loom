"""
tests/test_migration_safety.py -- Stage 30: the Stage 29 schema changes against
SYNTHETIC databases only. Schemas in tests/fixtures/ were generated from the real
historical database.py (Stage 27d = before any OAuth, Stage 28 = first OAuth
tables). No production database, credential or data is involved.
"""
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import database

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
NOW = "2026-01-01T00:00:00"


def _db(schema):
    fd, path = tempfile.mkstemp(suffix=".db", prefix="loom_test_migr_")
    os.close(fd)
    c = sqlite3.connect(path)
    if schema:
        c.executescript((FIX / schema).read_text())
    c.commit(); c.close()
    return path


@pytest.fixture
def mkdb(monkeypatch):
    paths = []

    def make(schema=None):
        p = _db(schema); paths.append(p)
        monkeypatch.setattr(database, "DB_PATH", p)
        monkeypatch.setattr(database, "USE_TURSO", False)
        return p
    yield make
    for p in paths:
        try: os.unlink(p)
        except OSError: pass


def q(path, sql, args=()):
    c = sqlite3.connect(path)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def add_users_and_dreams(path, n_users=3, dreams_each=2):
    c = sqlite3.connect(path)
    for i in range(1, n_users + 1):
        salt = f"salt{i}"
        c.execute("INSERT INTO users (username, email, password_hash, salt, created_at, email_verified) VALUES (?,?,?,?,?,1)",
                  (f"user{i}", f"user{i}@example.test", database._hash_password("Moonlit9pond", salt), salt, NOW))
        uid = c.execute("SELECT id FROM users WHERE username=?", (f"user{i}",)).fetchone()[0]
        for d in range(dreams_each):
            c.execute("INSERT INTO dreams (user_id, timestamp, raw_text) VALUES (?,?,?)", (uid, NOW, f"synthetic dream {i}-{d}"))
    c.commit(); c.close()


def snapshot(path):
    return (q(path, "SELECT id, username, email, password_hash, salt FROM users ORDER BY id"),
            q(path, "SELECT id, user_id, raw_text FROM dreams ORDER BY id"))


def schema_ok(path):
    cols = {r[1] for r in q(path, "PRAGMA table_info(oauth_flows)")}
    idx = {r[0] for r in q(path, "SELECT name FROM sqlite_master WHERE type='index'")}
    tables = {r[0] for r in q(path, "SELECT name FROM sqlite_master WHERE type='table'")}
    return ({"binding_hash", "purpose", "user_id"} <= cols and "idx_auth_identities_user_provider" in idx
            and {"auth_identities", "oauth_flows", "oauth_tickets"} <= tables)


# 1. clean installation
def test_clean_install_creates_everything_and_is_repeatable(mkdb):
    p = mkdb()
    database.init_db(); first = q(p, "SELECT type, name, sql FROM sqlite_master ORDER BY name")
    database.init_db(); database.init_db()
    assert schema_ok(p) and q(p, "SELECT type, name, sql FROM sqlite_master ORDER BY name") == first


# 2 + 6. existing installation without OAuth, several users with dreams
def test_existing_install_without_oauth_keeps_ids_dreams_and_passwords(mkdb):
    p = mkdb("schema_stage27d.sql")
    assert not q(p, "SELECT name FROM sqlite_master WHERE name='auth_identities'")
    add_users_and_dreams(p, n_users=4, dreams_each=3)
    before = snapshot(p)
    database.init_db()
    assert schema_ok(p) and snapshot(p) == before
    assert q(p, "SELECT COUNT(*) FROM dreams")[0][0] == 12
    for i in (1, 2, 3, 4):                                    # email/password accounts still sign in
        u = database.authenticate_user(f"user{i}", "Moonlit9pond")
        assert u and u["username"] == f"user{i}"
    assert not database.authenticate_user("user1", "wrong-password")
    database.init_db()                                        # second run: no change
    assert snapshot(p) == before


# 3. installation that already has linked Google identities (Stage 28 schema)
def test_existing_linked_identities_survive_and_stay_unique(mkdb):
    p = mkdb("schema_stage28.sql")
    add_users_and_dreams(p, 3, 1)
    c = sqlite3.connect(p)
    c.execute("INSERT INTO auth_identities (user_id, provider, subject, email, created_at) VALUES (1,'google','sub-a','user1@example.test',?)", (NOW,))
    c.execute("INSERT INTO auth_identities (user_id, provider, subject, email, created_at) VALUES (2,'google','sub-b','user2@example.test',?)", (NOW,))
    c.commit(); c.close()
    before = q(p, "SELECT * FROM auth_identities ORDER BY id")
    database.init_db()
    assert schema_ok(p) and q(p, "SELECT * FROM auth_identities ORDER BY id") == before
    c = sqlite3.connect(p)
    with pytest.raises(sqlite3.IntegrityError):               # same identity, second account
        c.execute("INSERT INTO auth_identities (user_id, provider, subject, created_at) VALUES (3,'google','sub-a',?)", (NOW,))
    with pytest.raises(sqlite3.IntegrityError):               # second Google identity, same account
        c.execute("INSERT INTO auth_identities (user_id, provider, subject, created_at) VALUES (1,'google','sub-z',?)", (NOW,))
    c.close()
    assert database.find_identity("google", "sub-a")["user_id"] == 1


# 4. duplicate provider identities: fail safe, leave data alone, report counts only
def test_duplicate_identities_do_not_break_startup_or_get_rewritten(mkdb, caplog):
    p = mkdb("schema_stage28.sql")
    add_users_and_dreams(p, 2, 1)
    c = sqlite3.connect(p)
    c.execute("INSERT INTO auth_identities (user_id, provider, subject, email, created_at) VALUES (1,'google','dup-1','secret-person@example.test',?)", (NOW,))
    c.execute("INSERT INTO auth_identities (user_id, provider, subject, email, created_at) VALUES (1,'google','dup-2','secret-person@example.test',?)", (NOW,))
    c.commit(); c.close()
    before_ids = q(p, "SELECT * FROM auth_identities ORDER BY id")
    with caplog.at_level(logging.WARNING, logger="loom"):
        database.init_db()                                    # must not raise
    assert q(p, "SELECT * FROM auth_identities ORDER BY id") == before_ids      # nothing merged or deleted
    assert not q(p, "SELECT name FROM sqlite_master WHERE name='idx_auth_identities_user_provider'")
    log = " ".join(r.getMessage() for r in caplog.records)
    assert "schema_warning" in log and "secret-person" not in log and "dup-1" not in log
    # the application layer still refuses to add yet another identity for that account
    assert database.link_identity_safely(1, "google", "dup-3", "x@example.test") != "linked"


def test_preflight_reports_counts_only_and_fails_on_conflicts(mkdb):
    p = mkdb("schema_stage28.sql")
    add_users_and_dreams(p, 2, 1)
    c = sqlite3.connect(p)
    c.execute("INSERT INTO auth_identities (user_id, provider, subject, email, created_at) VALUES (1,'google','dup-1','secret-person@example.test',?)", (NOW,))
    c.execute("INSERT INTO auth_identities (user_id, provider, subject, email, created_at) VALUES (1,'google','dup-2','secret-person@example.test',?)", (NOW,))
    c.commit(); c.close()
    before = Path(p).read_bytes()
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "preflight_auth_identities.py"), "--db", p],
                       capture_output=True, text=True, timeout=60, cwd=str(ROOT),
                       env={**os.environ, "TURSO_DATABASE_URL": "", "TURSO_AUTH_TOKEN": ""})
    assert r.returncode == 1 and "duplicate_user_provider_groups: 1" in r.stdout
    assert "secret-person" not in r.stdout + r.stderr and "dup-1" not in r.stdout + r.stderr
    assert Path(p).read_bytes() == before                      # byte-for-byte unchanged: read-only


def test_preflight_clean_and_no_table_cases_and_operator_flag(mkdb):
    p = mkdb("schema_stage27d.sql")
    env = {**os.environ, "TURSO_DATABASE_URL": "", "TURSO_AUTH_TOKEN": ""}
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts" / "preflight_auth_identities.py"), *a],
                                    capture_output=True, text=True, timeout=60, cwd=str(ROOT), env=env)
    r = run("--db", p)
    assert r.returncode == 0 and "no auth_identities table yet" in r.stdout
    assert run("--configured-backend").returncode == 2        # refuses without the explicit operator flag
    assert run().returncode == 2


# 5. interrupted / failed migration, at every possible statement
def test_failed_migration_at_any_statement_leaves_data_intact_and_recovers(mkdb, monkeypatch):
    p = mkdb("schema_stage27d.sql")
    add_users_and_dreams(p, 3, 2)
    before = snapshot(p)
    real = database._execute
    # count statements of a complete run on a copy
    n = {"i": 0}
    def counting(sql, params=()):
        n["i"] += 1; return real(sql, params)
    monkeypatch.setattr(database, "_execute", counting)
    database.init_db()
    total = n["i"]
    monkeypatch.setattr(database, "_execute", real)
    assert total > 20
    for fail_at in range(1, total + 1):
        p2 = mkdb("schema_stage27d.sql"); add_users_and_dreams(p2, 3, 2)
        k = {"i": 0}
        def flaky(sql, params=(), _at=fail_at):
            k["i"] += 1
            if k["i"] == _at:
                raise sqlite3.OperationalError("simulated crash")
            return real(sql, params)
        monkeypatch.setattr(database, "_execute", flaky)
        try:
            database.init_db()                                 # a few steps (the guarded index) absorb their own failure
        except sqlite3.OperationalError:
            pass
        monkeypatch.setattr(database, "_execute", real)
        assert snapshot(p2) == before                          # nothing lost after the crash
        database.init_db()                                     # next start finishes the job
        assert schema_ok(p2) and snapshot(p2) == before


# deletion + foreign keys
def test_account_deletion_removes_only_that_users_identity_and_data(mkdb):
    p = mkdb("schema_stage28.sql")
    database.init_db()
    add_users_and_dreams(p, 3, 2)
    c = sqlite3.connect(p)
    for uid in (1, 2, 3):
        c.execute("INSERT INTO auth_identities (user_id, provider, subject, created_at) VALUES (?,?,?,?)", (uid, "google", f"s{uid}", NOW))
    c.commit(); c.close()
    database.delete_account(2)
    assert q(p, "SELECT user_id FROM auth_identities ORDER BY user_id") == [(1,), (3,)]
    assert q(p, "SELECT COUNT(*) FROM dreams WHERE user_id=2")[0][0] == 0
    assert q(p, "SELECT COUNT(*) FROM dreams")[0][0] == 4 and q(p, "SELECT COUNT(*) FROM users")[0][0] == 2
    assert database.find_identity("google", "s2") is None


def test_schema_declares_no_foreign_keys_so_cleanup_is_the_applications_job(mkdb):
    p = mkdb(); database.init_db()
    for t in ("users", "dreams", "auth_identities", "oauth_flows", "oauth_tickets"):
        assert q(p, f"PRAGMA foreign_key_list({t})") == []
