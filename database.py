"""
Database layer for Loom.

Stores every logged dream, plus the structured data extracted from it,
its lightweight similarity fingerprint, and each person's account and
profile.

Two backends, chosen automatically:

  - Turso (hosted, SQLite-compatible) when TURSO_DATABASE_URL is set --
    this is what Render runs, because Render's free tier gives the app a
    brand-new, empty disk on every redeploy. A local SQLite file living
    on that disk would get wiped every time the app restarts, deletes
    every account, and that's exactly what kept happening. Turso's free
    tier is a real database that lives independently of the app, so it
    survives redeploys.
  - Local SQLite file (loom.db) when TURSO_DATABASE_URL isn't set --
    this is what running the app on your own machine uses, no account
    or internet connection required for local development.

Both speak the same SQL dialect (Turso *is* SQLite under the hood), and
both return rows that support `row["column"]` access, so every function
below reads the same either way -- only `_execute()` knows which
backend is actually in use.

Loom supports more than one person using the same deployment: every
dream, conversation, and profile belongs to a specific user_id, and a
simple username/password system (hashed with a random per-user salt --
nothing stored in plain text) keeps one person's archive private from
another's.
"""

import os
import json
import hashlib
import secrets
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Loaded here, not just assumed to already be loaded by whichever file
# imports this module first -- database.py reads TURSO_DATABASE_URL
# below at import time, so if something imports database before anything
# else has called load_dotenv(), these variables would silently still be
# unset even with a correct .env file sitting right there. Safe to call
# more than once (python-dotenv is a no-op if called again), and a no-op
# in production anyway since Render injects real environment variables
# directly rather than using a .env file.
load_dotenv()

TURSO_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")
USE_TURSO = bool(TURSO_URL)

if USE_TURSO:
    import libsql_client
    _client = libsql_client.create_client_sync(url=TURSO_URL, auth_token=TURSO_TOKEN)
else:
    import sqlite3
    DB_PATH = "loom.db"

# A login token is only good for this long before it stops working and
# the person has to log back in. Limits how long a leaked or
# forgotten-about token stays usable.
TOKEN_LIFETIME = timedelta(days=30)


def _execute(sql, params=()):
    """
    Run one SQL statement against whichever backend is active. Returns
    (rows, last_insert_rowid). `rows` is a list where each row supports
    both row["column"] and row[0] access, same shape either way, so
    every function below is backend-agnostic.
    """
    if USE_TURSO:
        rs = _client.execute(sql, list(params))
        return rs.rows, rs.last_insert_rowid

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return rows, last_id


def _column_exists(table, column):
    rows, _ = _execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in rows)


def _table_exists(table):
    rows, _ = _execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (table,)
    )
    return len(rows) > 0


def init_db():
    """
    Create every table if it doesn't exist yet, and migrate older,
    single-user versions of this database forward. Safe to call every
    time the app starts -- each step only runs once.
    """
    _execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            token TEXT UNIQUE,
            token_created_at TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # Migrations for databases created before email and token expiry existed.
    if not _column_exists("users", "email"):
        _execute("ALTER TABLE users ADD COLUMN email TEXT")
    if not _column_exists("users", "token_created_at"):
        _execute("ALTER TABLE users ADD COLUMN token_created_at TEXT")

    _execute("""
        CREATE TABLE IF NOT EXISTS dreams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            timestamp TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            symbols TEXT,
            emotions TEXT,
            people TEXT,
            settings TEXT,
            themes TEXT,
            interpretation TEXT,
            embedding TEXT,
            conversation TEXT
        )
    """)

    # Migration: a database from before accounts existed won't have a
    # user_id column on dreams yet. Adding it leaves old rows with
    # user_id = NULL -- ownerless, and every query below filters by
    # user_id, so they simply stop appearing for anyone. That's the
    # accepted cost of moving from one shared journal to real accounts.
    if not _column_exists("dreams", "user_id"):
        _execute("ALTER TABLE dreams ADD COLUMN user_id INTEGER")

    if not _column_exists("dreams", "conversation"):
        _execute("ALTER TABLE dreams ADD COLUMN conversation TEXT")

    # Profile used to be a single global row (id=1, no owner). Now it's
    # one row per user_id. There's no sane way to hand that one old
    # profile to a specific new account, so an old-shaped table gets
    # dropped and recreated rather than migrated.
    profile_exists = _table_exists("profile")
    if profile_exists and not _column_exists("profile", "user_id"):
        _execute("DROP TABLE profile")
        profile_exists = False

    if not profile_exists:
        _execute("""
            CREATE TABLE profile (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                birth_year INTEGER,
                birthplace TEXT,
                current_location TEXT,
                bio TEXT,
                picture_path TEXT
            )
        """)


# --- Accounts --------------------------------------------------------------
# Passwords are never stored in plain text. Each one is hashed with a
# random per-user salt using PBKDF2 -- standard-library only, so this
# adds no new dependency and no extra memory, which matters on a
# free-tier server that's already tight on RAM. "Logging in" just means
# proving you know the password that produces the same hash.

def _hash_password(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000
    ).hex()


def create_user(username, email, password):
    """Create a new account and return it with a fresh login token.
    Raises ValueError if the username is already taken."""
    rows, _ = _execute("SELECT id FROM users WHERE username = ?", (username,))
    if rows:
        raise ValueError("That username is already taken.")

    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    token = secrets.token_hex(32)
    now = datetime.now().isoformat()
    _, user_id = _execute("""
        INSERT INTO users (username, email, password_hash, salt, token, token_created_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (username, email, password_hash, salt, token, now, now))
    return {"id": user_id, "username": username, "token": token}


def authenticate_user(username, password):
    """Check a username/password pair. Returns the account with a fresh
    token on success, or None if the credentials don't match."""
    rows, _ = _execute("SELECT * FROM users WHERE username = ?", (username,))
    if not rows:
        return None
    row = rows[0]

    if _hash_password(password, row["salt"]) != row["password_hash"]:
        return None

    token = secrets.token_hex(32)
    _execute(
        "UPDATE users SET token = ?, token_created_at = ? WHERE id = ?",
        (token, datetime.now().isoformat(), row["id"])
    )
    return {"id": row["id"], "username": row["username"], "token": token}


def get_user_by_token(token):
    """Look up whoever a bearer token belongs to, or None if it isn't
    valid -- either because no such token exists, or because it's older
    than TOKEN_LIFETIME and has expired. Every authenticated endpoint
    uses this to decide whose data to read or write."""
    if not token:
        return None
    rows, _ = _execute(
        "SELECT id, username, token_created_at FROM users WHERE token = ?", (token,)
    )
    if not rows:
        return None
    row = rows[0]

    if row["token_created_at"]:
        try:
            issued = datetime.fromisoformat(row["token_created_at"])
            if datetime.now() - issued > TOKEN_LIFETIME:
                return None
        except ValueError:
            pass  # malformed timestamp from some older row -- fail open rather than lock someone out

    return {"id": row["id"], "username": row["username"]}


def clear_token(user_id):
    """Log a user out server-side by invalidating their current token --
    used by POST /logout. Without this, clearing the token from the
    browser alone would leave the old token still valid if anyone else
    had gotten hold of it."""
    _execute("UPDATE users SET token = NULL WHERE id = ?", (user_id,))


# --- Profile -----------------------------------------------------------

def get_profile(user_id):
    """Return this user's profile as a dict, or an empty-but-valid dict
    if they haven't filled one in yet."""
    rows, _ = _execute("SELECT * FROM profile WHERE user_id = ?", (user_id,))
    if not rows:
        return {
            "name": "", "birth_year": None, "birthplace": "",
            "current_location": "", "bio": "", "picture_path": ""
        }
    row = rows[0]
    return {
        "name": row["name"] or "",
        "birth_year": row["birth_year"],
        "birthplace": row["birthplace"] or "",
        "current_location": row["current_location"] or "",
        "bio": row["bio"] or "",
        "picture_path": row["picture_path"] or "",
    }


def save_profile(user_id, data):
    """
    Save this user's profile. `data` is a dict with keys name, birth_year,
    birthplace, current_location, bio, picture_path -- any missing key is
    treated as empty. Uses INSERT OR REPLACE since there's exactly one
    profile row per user_id.
    """
    _execute("""
        INSERT OR REPLACE INTO profile
            (user_id, name, birth_year, birthplace, current_location, bio, picture_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        data.get("name", ""),
        data.get("birth_year"),
        data.get("birthplace", ""),
        data.get("current_location", ""),
        data.get("bio", ""),
        data.get("picture_path", ""),
    ))


# --- Dreams --------------------------------------------------------------

def normalize_dream_date(date_str):
    """
    Turn a plain 'YYYY-MM-DD' date (what the date-only logging/editing UI
    sends) into a full ISO timestamp, anchored to right now's time-of-day --
    so a handful of backfilled dreams assigned to different dates still
    sort correctly within each day, and the stored value matches the
    format every other timestamp in this table already uses (always a
    full isoformat() string, never just a date). Raises ValueError with a
    message safe to show the user if date_str isn't a real calendar date
    in that shape.
    """
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("date must be in YYYY-MM-DD format")
    return datetime.combine(d, datetime.now().time()).isoformat()


def insert_dream(user_id, raw_text, extracted, interpretation, embedding, timestamp=None):
    """
    Save a new dream to the database, owned by user_id.

    extracted: dict with keys symbols, emotions, people, settings, themes
               (each a list of strings) -- these get stored as JSON text,
               since SQLite doesn't have a native "list" column type.
    embedding: this dream's word-overlap fingerprint (see engine.py),
               also stored as JSON text.
    timestamp: optional pre-built ISO timestamp (see normalize_dream_date)
               for logging a dream from an earlier night rather than right
               now -- defaults to the current moment when omitted, same as
               before this parameter existed.

    Returns the new dream's id.
    """
    _, new_id = _execute("""
        INSERT INTO dreams (user_id, timestamp, raw_text, symbols, emotions, people,
                             settings, themes, interpretation, embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        timestamp or datetime.now().isoformat(),
        raw_text,
        json.dumps(extracted.get("symbols", []), ensure_ascii=False),
        json.dumps(extracted.get("emotions", []), ensure_ascii=False),
        json.dumps(extracted.get("people", []), ensure_ascii=False),
        json.dumps(extracted.get("settings", []), ensure_ascii=False),
        json.dumps(extracted.get("themes", []), ensure_ascii=False),
        interpretation,
        json.dumps(embedding),
    ))
    return new_id


def update_dream(user_id, dream_id, raw_text, extracted, interpretation, embedding):
    """
    Overwrite an existing dream's text and interpretation in place (the
    person edited and re-interpreted it), scoped to user_id so nobody can
    edit someone else's dream even by guessing its id. The timestamp
    stays as the original logging time -- an edit doesn't bump a dream
    to "now" in the archive, which would be confusing. The follow-up
    conversation is cleared: it was grounded in the old dream text and
    old interpretation, so keeping it around after an edit would have
    the chat referencing things that may no longer be accurate.

    Returns True if a dream was actually updated, False if no dream with
    that id belongs to this user (lets the caller 404 instead of
    silently doing nothing). Checked up front with a plain SELECT, rather
    than relying on an UPDATE's affected-row count, since _execute's
    (rows, last_insert_rowid) shape doesn't carry that for every backend.
    """
    rows, _ = _execute("SELECT id FROM dreams WHERE id = ? AND user_id = ?", (dream_id, user_id))
    if not rows:
        return False

    _execute("""
        UPDATE dreams
        SET raw_text = ?, symbols = ?, emotions = ?, people = ?, settings = ?,
            themes = ?, interpretation = ?, embedding = ?, conversation = '[]'
        WHERE id = ? AND user_id = ?
    """, (
        raw_text,
        json.dumps(extracted.get("symbols", []), ensure_ascii=False),
        json.dumps(extracted.get("emotions", []), ensure_ascii=False),
        json.dumps(extracted.get("people", []), ensure_ascii=False),
        json.dumps(extracted.get("settings", []), ensure_ascii=False),
        json.dumps(extracted.get("themes", []), ensure_ascii=False),
        interpretation,
        json.dumps(embedding),
        dream_id,
        user_id,
    ))
    return True


def update_dream_timestamp(user_id, dream_id, timestamp):
    """
    Overwrite just a dream's logged date/time, leaving its text,
    interpretation, and conversation untouched -- for backdating an entry
    (e.g. several real dreams typed in together today, each actually from
    a different earlier night) rather than correcting what it says.
    Scoped to user_id, same as update_dream, so nobody can re-date
    another person's dream even by guessing its id.

    Returns True if a dream was actually updated, False if no dream with
    that id belongs to this user.
    """
    rows, _ = _execute("SELECT id FROM dreams WHERE id = ? AND user_id = ?", (dream_id, user_id))
    if not rows:
        return False
    _execute(
        "UPDATE dreams SET timestamp = ? WHERE id = ? AND user_id = ?",
        (timestamp, dream_id, user_id)
    )
    return True


def update_dream_conversation(user_id, dream_id, messages):
    """
    Save the ongoing conversation about a specific dream. Scoped to
    user_id too, so nobody can overwrite another person's conversation
    even if they guessed a dream id.
    """
    _execute(
        "UPDATE dreams SET conversation = ? WHERE id = ? AND user_id = ?",
        (json.dumps(messages, ensure_ascii=False), dream_id, user_id)
    )


def update_embedding(user_id, dream_id, embedding):
    """
    Overwrite just a dream's embedding column, leaving everything else
    (text, interpretation, conversation) untouched. Used by
    backfill_pinecone.py to re-embed old dreams that still carry a
    pre-Voyage-AI word-overlap fingerprint (a list of strings) instead
    of a real numeric vector -- update_dream() would also wipe the
    conversation and requires re-supplying every other field, which is
    overkill (and risky) for fixing one column.
    """
    _execute(
        "UPDATE dreams SET embedding = ? WHERE id = ? AND user_id = ?",
        (json.dumps(embedding), dream_id, user_id)
    )


def _row_to_dream(row):
    return {
        "id": row["id"],
        "timestamp": row["timestamp"],
        "raw_text": row["raw_text"],
        "symbols": json.loads(row["symbols"] or "[]"),
        "emotions": json.loads(row["emotions"] or "[]"),
        "people": json.loads(row["people"] or "[]"),
        "settings": json.loads(row["settings"] or "[]"),
        "themes": json.loads(row["themes"] or "[]"),
        "interpretation": row["interpretation"],
        "embedding": json.loads(row["embedding"] or "[]"),
        "conversation": json.loads(row["conversation"] or "[]"),
    }


def get_all_dreams(user_id):
    """Return every dream belonging to this user, oldest first."""
    rows, _ = _execute(
        "SELECT * FROM dreams WHERE user_id = ? ORDER BY timestamp ASC", (user_id,)
    )
    return [_row_to_dream(row) for row in rows]


def get_dream(user_id, dream_id):
    """Return one dream by id, but only if it belongs to this user --
    otherwise None, same as if it didn't exist. This is what keeps one
    person from continuing a conversation on someone else's dream even
    if they guessed or saw its id."""
    rows, _ = _execute(
        "SELECT * FROM dreams WHERE id = ? AND user_id = ?", (dream_id, user_id)
    )
    if not rows:
        return None
    return _row_to_dream(rows[0])


def ping():
    """
    Cheap connectivity check for /health: True if the database (Turso or
    local SQLite fallback) actually answers a trivial query right now,
    False if it doesn't (wrong credentials, Turso outage, network
    issue). SELECT 1 rather than touching any real table, so this never
    depends on the schema already existing.
    """
    try:
        _execute("SELECT 1")
        return True
    except Exception:
        return False


def delete_dream(user_id, dream_id):
    """
    Permanently remove one dream, scoped to user_id so nobody can delete
    someone else's dream even by guessing its id. Returns True if a
    dream was actually deleted, False if no dream with that id belongs
    to this user (lets the caller 404 instead of silently doing
    nothing) -- same pattern as update_dream's existence check.
    """
    rows, _ = _execute("SELECT id FROM dreams WHERE id = ? AND user_id = ?", (dream_id, user_id))
    if not rows:
        return False
    _execute("DELETE FROM dreams WHERE id = ? AND user_id = ?", (dream_id, user_id))
    return True


def count_dreams(user_id):
    rows, _ = _execute("SELECT COUNT(*) FROM dreams WHERE user_id = ?", (user_id,))
    return rows[0][0]
