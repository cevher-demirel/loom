"""
Database layer for Loom.

Stores every logged dream, plus the structured data extracted from it,
its lightweight similarity fingerprint, and each person's account and
profile, in a local SQLite database.

Loom supports more than one person using the same deployment: every
dream, conversation, and profile belongs to a specific user_id, and a
simple username/password system (hashed with a random per-user salt --
nothing stored in plain text) keeps one person's archive private from
another's.
"""

import sqlite3
import json
import hashlib
import secrets
from datetime import datetime

DB_PATH = "loom.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def _column_exists(cur, table, column):
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def init_db():
    """
    Create every table if it doesn't exist yet, and migrate older,
    single-user versions of this database forward. Safe to call every
    time the app starts -- each step only runs once.
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            token TEXT UNIQUE,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
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
    conn.commit()

    # Migration: a database from before accounts existed won't have a
    # user_id column on dreams yet. Adding it leaves old rows with
    # user_id = NULL -- ownerless, and every query below filters by
    # user_id, so they simply stop appearing for anyone. That's the
    # accepted cost of moving from one shared journal to real accounts.
    if not _column_exists(cur, "dreams", "user_id"):
        cur.execute("ALTER TABLE dreams ADD COLUMN user_id INTEGER")
        conn.commit()

    if not _column_exists(cur, "dreams", "conversation"):
        cur.execute("ALTER TABLE dreams ADD COLUMN conversation TEXT")
        conn.commit()

    # Profile used to be a single global row (id=1, no owner). Now it's
    # one row per user_id. There's no sane way to hand that one old
    # profile to a specific new account, so an old-shaped table gets
    # dropped and recreated rather than migrated.
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='profile'")
    profile_exists = cur.fetchone() is not None
    if profile_exists and not _column_exists(cur, "profile", "user_id"):
        cur.execute("DROP TABLE profile")
        conn.commit()
        profile_exists = False

    if not profile_exists:
        cur.execute("""
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
        conn.commit()

    conn.close()


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


def create_user(username, password):
    """Create a new account and return it with a fresh login token.
    Raises ValueError if the username is already taken."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = ?", (username,))
    if cur.fetchone() is not None:
        conn.close()
        raise ValueError("That username is already taken.")

    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    token = secrets.token_hex(32)
    cur.execute("""
        INSERT INTO users (username, password_hash, salt, token, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (username, password_hash, salt, token, datetime.now().isoformat()))
    conn.commit()
    user_id = cur.lastrowid
    conn.close()
    return {"id": user_id, "username": username, "token": token}


def authenticate_user(username, password):
    """Check a username/password pair. Returns the account with a fresh
    token on success, or None if the credentials don't match."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return None

    if _hash_password(password, row["salt"]) != row["password_hash"]:
        conn.close()
        return None

    token = secrets.token_hex(32)
    cur.execute("UPDATE users SET token = ? WHERE id = ?", (token, row["id"]))
    conn.commit()
    conn.close()
    return {"id": row["id"], "username": row["username"], "token": token}


def get_user_by_token(token):
    """Look up whoever a bearer token belongs to, or None if it isn't
    valid. Every authenticated endpoint uses this to decide whose data
    to read or write."""
    if not token:
        return None
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM users WHERE token = ?", (token,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return {"id": row["id"], "username": row["username"]}


# --- Profile -----------------------------------------------------------

def get_profile(user_id):
    """Return this user's profile as a dict, or an empty-but-valid dict
    if they haven't filled one in yet."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM profile WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()

    if row is None:
        return {
            "name": "", "birth_year": None, "birthplace": "",
            "current_location": "", "bio": "", "picture_path": ""
        }
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
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
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
    conn.commit()
    conn.close()


# --- Dreams --------------------------------------------------------------

def insert_dream(user_id, raw_text, extracted, interpretation, embedding):
    """
    Save a new dream to the database, owned by user_id.

    extracted: dict with keys symbols, emotions, people, settings, themes
               (each a list of strings) -- these get stored as JSON text,
               since SQLite doesn't have a native "list" column type.
    embedding: this dream's word-overlap fingerprint (see engine.py),
               also stored as JSON text.

    Returns the new dream's id.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO dreams (user_id, timestamp, raw_text, symbols, emotions, people,
                             settings, themes, interpretation, embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        datetime.now().isoformat(),
        raw_text,
        json.dumps(extracted.get("symbols", []), ensure_ascii=False),
        json.dumps(extracted.get("emotions", []), ensure_ascii=False),
        json.dumps(extracted.get("people", []), ensure_ascii=False),
        json.dumps(extracted.get("settings", []), ensure_ascii=False),
        json.dumps(extracted.get("themes", []), ensure_ascii=False),
        interpretation,
        json.dumps(embedding),
    ))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def update_dream_conversation(user_id, dream_id, messages):
    """
    Save the ongoing conversation about a specific dream. Scoped to
    user_id too, so nobody can overwrite another person's conversation
    even if they guessed a dream id.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE dreams SET conversation = ? WHERE id = ? AND user_id = ?",
        (json.dumps(messages, ensure_ascii=False), dream_id, user_id)
    )
    conn.commit()
    conn.close()


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
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM dreams WHERE user_id = ? ORDER BY timestamp ASC", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return [_row_to_dream(row) for row in rows]


def get_dream(user_id, dream_id):
    """Return one dream by id, but only if it belongs to this user --
    otherwise None, same as if it didn't exist. This is what keeps one
    person from continuing a conversation on someone else's dream even
    if they guessed or saw its id."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM dreams WHERE id = ? AND user_id = ?", (dream_id, user_id))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return _row_to_dream(row)


def count_dreams(user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM dreams WHERE user_id = ?", (user_id,))
    count = cur.fetchone()[0]
    conn.close()
    return count
