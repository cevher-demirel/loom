"""
Database layer for Loominous.

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

Loominous supports more than one person using the same deployment: every
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

# A password-reset link is only good for this long after it's emailed --
# much shorter than a login token, since this one grants "set a brand
# new password," not just "read my dreams," and it's sitting in an
# inbox rather than a browser's own storage.
RESET_TOKEN_LIFETIME = timedelta(hours=1)

# A verification link gets to sit in an inbox much longer than a
# password-reset link before it's considered stale -- confirming an
# email isn't time-sensitive the way "someone may be trying to take
# over this account right now" is, so this is generous on purpose.
VERIFY_TOKEN_LIFETIME = timedelta(hours=24)


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


def _row_to_dict(row):
    """
    Turn one result row into a plain {column: value} dict, either
    backend. sqlite3.Row supports dict() directly (it implements
    keys()), but libsql_client's Row is a plain Sequence with no
    keys() -- dict() on one of those would try to read it as an
    iterable of (key, value) pairs and blow up. Its own .asdict()
    does the right thing, so this just picks whichever is available.
    """
    return row.asdict() if hasattr(row, "asdict") else dict(row)


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

    # Legacy column from the old guest-mode feature (removed) -- kept here,
    # always 0 for every row created from now on, rather than dropped, so
    # this migration stays additive-only and any already-deployed database
    # doesn't need a destructive ALTER TABLE ... DROP COLUMN to catch up.
    if not _column_exists("users", "is_guest"):
        _execute("ALTER TABLE users ADD COLUMN is_guest INTEGER NOT NULL DEFAULT 0")

    # Password-reset tokens -- deliberately a separate column from the
    # login `token` above, rather than reusing it, so a reset token can
    # never double as a login token. Whoever holds one should only be
    # able to set a new password with it, never also read the account's
    # dreams with it.
    if not _column_exists("users", "reset_token"):
        _execute("ALTER TABLE users ADD COLUMN reset_token TEXT")
    if not _column_exists("users", "reset_token_created_at"):
        _execute("ALTER TABLE users ADD COLUMN reset_token_created_at TEXT")

    # Email verification. email_verified defaults to 0 so every existing
    # row (created before this column existed) reads as unverified --
    # harmless, since the frontend only ever nags about it, never blocks
    # on it, and an account with no email at all is treated as having
    # nothing to verify (see create_user, which sets this to 1 for
    # those). verify_token follows the same separate-column reasoning
    # as reset_token above: a verification link should only ever be
    # able to confirm an email, never double as a login or reset token.
    if not _column_exists("users", "email_verified"):
        _execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
    if not _column_exists("users", "verify_token"):
        _execute("ALTER TABLE users ADD COLUMN verify_token TEXT")
    if not _column_exists("users", "verify_token_created_at"):
        _execute("ALTER TABLE users ADD COLUMN verify_token_created_at TEXT")

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

    if not _column_exists("dreams", "location"):
        _execute("ALTER TABLE dreams ADD COLUMN location TEXT")

    # {text: icon category} for every symbol/theme, assigned by the model
    # itself at extraction time (see engine.ICON_CATEGORIES) rather than
    # guessed from keywords client-side. A dream logged before this column
    # existed reads back as '{}' (see get_dream/get_all_dreams below), so
    # its symbol row is simply empty until it's edited and re-extracted --
    # there's no sane way to retroactively classify old symbols without
    # another Claude call per dream.
    if not _column_exists("dreams", "symbol_icons"):
        _execute("ALTER TABLE dreams ADD COLUMN symbol_icons TEXT")

    # What the person themselves tagged at entry (see the mood chips in
    # #panel-log), stored separately from "emotions" -- the AI's own
    # read of the text -- so the two can be shown side by side later.
    # Entirely optional; a dream logged before this column existed, or
    # one where nothing was tagged, simply reads back as '[]'.
    if not _column_exists("dreams", "emotions_reported"):
        _execute("ALTER TABLE dreams ADD COLUMN emotions_reported TEXT")

    # The AI's own read of this dream's emotional tone, restricted to the
    # same eight-word Plutchik set emotions_reported above is tagged
    # from (see engine.extract_dream_data) -- distinct from "emotions",
    # which stays free text. Exists purely so "You said" and "The dream
    # read" can be compared in the same vocabulary; a dream logged before
    # this column existed reads back as '[]', same as emotions_reported.
    if not _column_exists("dreams", "emotions_plutchik"):
        _execute("ALTER TABLE dreams ADD COLUMN emotions_plutchik TEXT")

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
                picture_path TEXT,
                birth_date TEXT,
                gender TEXT,
                relationship_status TEXT,
                picture_data TEXT
            )
        """)

    # birth_date/gender/relationship_status/picture_data were added after
    # birth_year/picture_path -- an existing table from before this needs
    # them bolted on. birth_year itself is left alone (not dropped, not
    # backfilled): _profile_context still reads it as a fallback for
    # whatever profile was saved before "Date of birth" replaced "Birth
    # year" in the UI, so an old profile doesn't lose its only age signal
    # just because no one's re-saved it since.
    for column in ("birth_date", "gender", "relationship_status", "picture_data"):
        if not _column_exists("profile", column):
            _execute(f"ALTER TABLE profile ADD COLUMN {column} TEXT")

    # One conversation thread per (user, symbol) -- not per dream. The same
    # symbol can turn up across many dreams, and tapping into it from any
    # one of them should land on the same ongoing thread, not a fresh one
    # per occurrence. symbol_key is the same normalized (trimmed,
    # lowercased) form the frontend already uses to group occurrences of a
    # symbol together; symbol_label keeps one real-cased copy for display.
    _execute("""
        CREATE TABLE IF NOT EXISTS symbol_chats (
            user_id INTEGER NOT NULL,
            symbol_key TEXT NOT NULL,
            symbol_label TEXT NOT NULL,
            conversation TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY (user_id, symbol_key)
        )
    """)

    # The Loom Map's data foundation -- added for the Journal/Loom Map/
    # Insights/Settings rework. Two tables, both additive and both
    # entirely user-authored (nothing in engine.py ever writes to
    # either), so "Your meaning" can never be silently overwritten by
    # an AI call and a feedback click can never be mistaken for the
    # model having learned anything:
    #
    #   - personal_meanings: what a symbol/emotion/person/place means
    #     to THIS user, in their own words -- kept structurally apart
    #     from any AI-generated reading (see the brief's Personal
    #     Meaning section). subject_type/subject_key mirror the same
    #     normalized-key convention symbol_chats already uses above,
    #     widened to cover the other Loom Map node types.
    #
    #   - connection_feedback: "this feels relevant / not relevant /
    #     I've confirmed this" on a suggested connection or a
    #     Discoveries card. connection_key is a deterministic id the
    #     caller derives from what's being rated (e.g. two sorted
    #     "type:key" subjects joined together, or a discovery's own
    #     id) rather than a foreign key into a connections table,
    #     because connections themselves are computed from the dreams
    #     a user already has rather than stored -- there's nothing
    #     else to join against yet. Recording this is explicit user
    #     data, stored because the brief asks for it to be captured
    #     even though nothing downstream retrains or alters the model
    #     on it yet -- see save_connection_feedback below, and don't
    #     let any UI copy built on this table imply otherwise.
    _execute("""
        CREATE TABLE IF NOT EXISTS personal_meanings (
            user_id INTEGER NOT NULL,
            subject_type TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            subject_label TEXT NOT NULL,
            meaning TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, subject_type, subject_key)
        )
    """)
    _execute("""
        CREATE TABLE IF NOT EXISTS connection_feedback (
            user_id INTEGER NOT NULL,
            connection_key TEXT NOT NULL,
            status TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, connection_key)
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
    """
    Create a new account and return it with a fresh login token. Raises
    ValueError if the username is already taken.

    Verification-via-emailed-link is legacy-only: every account created
    here is marked email_verified=1 (confirmed, trivially) right away,
    whether or not it even has an email. Email itself is already
    required and taken at face value at signup time (see main.py's
    signup()), so there's no separate "now also click a link" step for
    a brand-new account -- that would just be friction with no real
    benefit. The verify_token / "please confirm your email" nudge
    machinery elsewhere in this file (verify_email_with_token,
    create_email_verify_token, and main.py's GET /account, POST
    /verify-email, POST /resend-verification) still exists and still
    works -- it's just never reached by a *new* signup anymore, only by
    whatever account already happened to be sitting unverified from
    before this stopped being the rule for new ones.

    The returned dict carries verify_token (always None now) alongside
    the usual id/username/token for symmetry with that older flow --
    harmless either way, since it's extra beyond what AuthOut (main.py's
    signup response shape) declares and gets silently dropped from what
    the client actually sees (pydantic ignores unknown keys by default).
    """
    rows, _ = _execute("SELECT id FROM users WHERE username = ?", (username,))
    if rows:
        raise ValueError("That username is already taken.")
    # Same guard as create_password_reset_token's lookup and
    # authenticate_user's: `email != ''` so this can never match a
    # legacy guest-account row's blank email (see the is_guest column's
    # own comment above). Without this check, signing
    # up twice with the same email just silently created a second
    # account that /forgot-password's single-row lookup would then pick
    # between arbitrarily -- better to tell the person up front that an
    # account with this email already exists than let that happen.
    rows, _ = _execute("SELECT id FROM users WHERE email = ? AND email != ''", (email,))
    if rows:
        raise ValueError("An account with that email already exists. Try logging in, or use \"Forgot your password?\" if you don't remember it.")

    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    token = secrets.token_hex(32)
    now = datetime.now().isoformat()

    email_verified = 1
    verify_token = None

    _, user_id = _execute("""
        INSERT INTO users (username, email, password_hash, salt, token, token_created_at,
                            created_at, email_verified, verify_token, verify_token_created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        username, email, password_hash, salt, token, now, now,
        email_verified, verify_token, now if verify_token else None,
    ))
    return {
        "id": user_id, "username": username, "token": token,
        "email": email, "email_verified": bool(email_verified), "verify_token": verify_token,
    }


def authenticate_user(identifier, password):
    """
    Check a username-or-email + password pair -- login accepts either
    one in the same field, so this looks a person up by whichever they
    actually typed rather than main.py needing to guess which it was.
    Username matches exactly (case-sensitive, as it always has); email
    matches case-insensitively, and only against a real email (the
    `email != ''` guard keeps this from ever matching a legacy guest
    row's empty string). Returns the account with a fresh token on success,
    or None if nothing matches or the password is wrong.
    """
    rows, _ = _execute(
        "SELECT * FROM users WHERE username = ? OR (email = ? AND email != '')",
        (identifier, identifier.strip().lower())
    )
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


def verify_password(user_id, password):
    """
    Check a password against one specific account by id, with no other
    side effect -- unlike authenticate_user(), this never rotates the
    login token. Used where the caller already knows who they are from
    a valid bearer token and just needs a second factor for something
    irreversible (account deletion): looking the account up by id rather
    than username/email also means there's no re-parsing of "who is
    this" at all, just "is this really them." Returns True/False.
    """
    rows, _ = _execute("SELECT salt, password_hash FROM users WHERE id = ?", (user_id,))
    if not rows:
        return False
    row = rows[0]
    return _hash_password(password, row["salt"]) == row["password_hash"]


def create_password_reset_token(email):
    """
    Start a password-reset flow for whoever owns this email, if anyone
    does. Returns {"id", "username", "email", "reset_token"} on success,
    or None if no account has this email on file. The caller (POST
    /forgot-password) gives the exact same response to the person
    either way -- this return value only ever decides whether an email
    actually goes out, never what they see, so this never becomes a way
    to probe which emails have accounts here.

    Legacy guest-account rows are never matched -- they were created
    with email="" (see the is_guest column's own comment above), and
    this filters those out explicitly rather than relying on no one
    ever guessing an empty string.

    If more than one account somehow shares the same email (nothing
    here enforces uniqueness on it, only on username), this resets
    whichever one the query happens to return first -- an acceptable
    rough edge for a personal project, not something worth a schema
    migration to prevent.
    """
    rows, _ = _execute("SELECT id, username FROM users WHERE email = ? AND email != ''", (email,))
    if not rows:
        return None
    row = rows[0]
    reset_token = secrets.token_hex(32)
    _execute(
        "UPDATE users SET reset_token = ?, reset_token_created_at = ? WHERE id = ?",
        (reset_token, datetime.now().isoformat(), row["id"])
    )
    return {"id": row["id"], "username": row["username"], "email": email, "reset_token": reset_token}


def reset_password_with_token(reset_token, new_password):
    """
    Finish a password-reset flow: if reset_token is real and hasn't
    expired (RESET_TOKEN_LIFETIME), set the new password, consume the
    token so it can't be used a second time, and issue a brand new
    login token too -- a password reset usually means someone untrusted
    may have had access, so whatever session existed before is
    invalidated along with it, the same way clear_token() does for an
    explicit logout.

    Returns the account with its fresh login token (same shape as
    authenticate_user) on success, so the frontend can sign the person
    straight in after resetting rather than making them log in again
    right after. Returns None if the token is missing, unrecognized, or
    expired.
    """
    rows, _ = _execute(
        "SELECT id, username, reset_token_created_at FROM users WHERE reset_token = ?",
        (reset_token,)
    )
    if not rows:
        return None
    row = rows[0]

    if not row["reset_token_created_at"]:
        return None
    try:
        issued = datetime.fromisoformat(row["reset_token_created_at"])
        if datetime.now() - issued > RESET_TOKEN_LIFETIME:
            return None
    except ValueError:
        return None

    salt = secrets.token_hex(16)
    password_hash = _hash_password(new_password, salt)
    login_token = secrets.token_hex(32)
    _execute("""
        UPDATE users
        SET password_hash = ?, salt = ?, reset_token = NULL, reset_token_created_at = NULL,
            token = ?, token_created_at = ?
        WHERE id = ?
    """, (password_hash, salt, login_token, datetime.now().isoformat(), row["id"]))
    return {"id": row["id"], "username": row["username"], "token": login_token}


def verify_email_with_token(verify_token):
    """
    Confirm an email address: if verify_token is real and hasn't expired
    (VERIFY_TOKEN_LIFETIME), mark the account verified and consume the
    token. Returns True on success, False if the token is missing,
    unrecognized, or expired -- never raises, since an expired or
    double-clicked verification link is an everyday occurrence, not an
    error.
    """
    rows, _ = _execute(
        "SELECT id, verify_token_created_at FROM users WHERE verify_token = ?", (verify_token,)
    )
    if not rows:
        return False
    row = rows[0]

    if not row["verify_token_created_at"]:
        return False
    try:
        issued = datetime.fromisoformat(row["verify_token_created_at"])
        if datetime.now() - issued > VERIFY_TOKEN_LIFETIME:
            return False
    except ValueError:
        return False

    _execute(
        "UPDATE users SET email_verified = 1, verify_token = NULL, verify_token_created_at = NULL WHERE id = ?",
        (row["id"],)
    )
    return True


def create_email_verify_token(user_id):
    """
    (Re)issue a verification token for an already-authenticated user --
    backs POST /resend-verification. Returns the new token, or None if
    this account has no email on file (nothing to verify) or is already
    verified (nothing to do). Safe to call repeatedly: each call
    replaces whatever token existed before, so only the most recently
    sent email's link still works.
    """
    rows, _ = _execute("SELECT email, email_verified FROM users WHERE id = ?", (user_id,))
    if not rows:
        return None
    row = rows[0]
    if not row["email"] or row["email_verified"]:
        return None

    verify_token = secrets.token_hex(32)
    _execute(
        "UPDATE users SET verify_token = ?, verify_token_created_at = ? WHERE id = ?",
        (verify_token, datetime.now().isoformat(), user_id)
    )
    return verify_token


def set_account_email(user_id, email):
    """
    Add or change the email on file for an already-logged-in account --
    backs POST /account/email. This is how a legacy account created
    before email was required gets one on file after the fact: without
    it, create_password_reset_token has
    nothing to match against, so "forgot password" is permanently a
    dead end for that account.

    Always marks the new address unverified and issues a fresh
    verify_token in the same call (rather than requiring a separate
    create_email_verify_token round trip), since create_email_verify_token
    would otherwise need the email already written and verified=0 first
    -- the caller can email this token immediately. Returns the new
    verify_token, or None if user_id doesn't match any account. Raises
    ValueError (same as create_user's username check) if some other
    account already has this email on file -- otherwise two accounts
    would end up sharing one email and /forgot-password's single-row
    lookup would pick between them arbitrarily.
    """
    rows, _ = _execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not rows:
        return None
    rows, _ = _execute(
        "SELECT id FROM users WHERE email = ? AND email != '' AND id != ?", (email, user_id)
    )
    if rows:
        raise ValueError("An account with that email already exists.")
    verify_token = secrets.token_hex(32)
    _execute(
        "UPDATE users SET email = ?, email_verified = 0, verify_token = ?, verify_token_created_at = ? WHERE id = ?",
        (email, verify_token, datetime.now().isoformat(), user_id)
    )
    return verify_token


def get_user_by_token(token):
    """Look up whoever a bearer token belongs to, or None if it isn't
    valid -- either because no such token exists, or because it's older
    than TOKEN_LIFETIME and has expired. Every authenticated endpoint
    uses this to decide whose data to read or write."""
    if not token:
        return None
    rows, _ = _execute(
        "SELECT id, username, token_created_at, email, email_verified FROM users WHERE token = ?", (token,)
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

    return {
        "id": row["id"], "username": row["username"],
        "email": row["email"] or "", "email_verified": bool(row["email_verified"]),
    }


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
            "current_location": "", "bio": "", "picture_path": "",
            "birth_date": "", "gender": "", "relationship_status": "",
            "picture_data": "",
        }
    row = rows[0]
    return {
        "name": row["name"] or "",
        "birth_year": row["birth_year"],
        "birthplace": row["birthplace"] or "",
        "current_location": row["current_location"] or "",
        "bio": row["bio"] or "",
        "picture_path": row["picture_path"] or "",
        "birth_date": row["birth_date"] or "",
        "gender": row["gender"] or "",
        "relationship_status": row["relationship_status"] or "",
        "picture_data": row["picture_data"] or "",
    }


def save_profile(user_id, data):
    """
    Save this user's profile. `data` is a dict with keys name, birth_year,
    birthplace, current_location, bio, picture_path, birth_date, gender,
    relationship_status, picture_data -- any missing key is treated as
    empty. Uses INSERT OR REPLACE since there's exactly one profile row
    per user_id -- which also means every one of these columns gets
    rewritten on every save, birth_year included: a profile saved through
    today's UI (which only ever sends birth_date now) naturally clears
    whatever birth_year an older save had left there.
    """
    _execute("""
        INSERT OR REPLACE INTO profile
            (user_id, name, birth_year, birthplace, current_location, bio, picture_path,
             birth_date, gender, relationship_status, picture_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        data.get("name", ""),
        data.get("birth_year"),
        data.get("birthplace", ""),
        data.get("current_location", ""),
        data.get("bio", ""),
        data.get("picture_path", ""),
        data.get("birth_date", ""),
        data.get("gender", ""),
        data.get("relationship_status", ""),
        data.get("picture_data", ""),
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


def insert_dream(user_id, raw_text, extracted, interpretation, embedding, timestamp=None, location=None, emotions_reported=None):
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
    location: optional free-text place this dream was logged from (e.g.
               "Istanbul"), for someone backfilling dreams from different
               chapters of their life -- entirely optional, same as before
               this parameter existed.
    emotions_reported: optional list of mood labels the person themselves
               picked when logging the dream (see the mood chips in
               #panel-log) -- distinct from extracted["emotions"], which is
               the AI's own read of the text. Entirely optional, same as
               before this parameter existed.

    Returns the new dream's id.
    """
    _, new_id = _execute("""
        INSERT INTO dreams (user_id, timestamp, raw_text, symbols, emotions, people,
                             settings, themes, interpretation, embedding, location, symbol_icons,
                             emotions_reported, emotions_plutchik)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        location or None,
        json.dumps(extracted.get("symbol_icons", {}), ensure_ascii=False),
        json.dumps(emotions_reported or [], ensure_ascii=False),
        json.dumps(extracted.get("emotions_plutchik", []), ensure_ascii=False),
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
            themes = ?, interpretation = ?, embedding = ?, conversation = '[]',
            symbol_icons = ?, emotions_plutchik = ?
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
        json.dumps(extracted.get("symbol_icons", {}), ensure_ascii=False),
        json.dumps(extracted.get("emotions_plutchik", []), ensure_ascii=False),
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


def update_dream_location(user_id, dream_id, location):
    """
    Overwrite just a dream's logged place -- same idea as
    update_dream_timestamp, for backfilling or correcting where a dream
    was from without touching anything else about it. An empty string
    clears it back to "no location set" rather than being stored as a
    literal empty value, so it reads the same as a dream that never had
    one.

    Returns True if a dream was actually updated, False if no dream with
    that id belongs to this user.
    """
    rows, _ = _execute("SELECT id FROM dreams WHERE id = ? AND user_id = ?", (dream_id, user_id))
    if not rows:
        return False
    _execute(
        "UPDATE dreams SET location = ? WHERE id = ? AND user_id = ?",
        (location.strip() or None, dream_id, user_id)
    )
    return True


def update_dream_emotions_plutchik(user_id, dream_id, plutchik):
    """
    Backfills just emotions_plutchik on a dream logged before that field
    existed -- see main.py's GET /dreams/{id}/emotions, which computes it
    with engine.classify_emotions_plutchik() from what's already stored
    (never re-running the full extraction or interpretation), then calls
    this once to persist it so the same dream never needs to go through
    that again. Leaves raw_text, the interpretation, emotions_reported,
    and everything else on the row completely untouched.

    Returns True if a dream was actually updated, False if no dream with
    that id belongs to this user.
    """
    rows, _ = _execute("SELECT id FROM dreams WHERE id = ? AND user_id = ?", (dream_id, user_id))
    if not rows:
        return False
    _execute(
        "UPDATE dreams SET emotions_plutchik = ? WHERE id = ? AND user_id = ?",
        (json.dumps(plutchik), dream_id, user_id)
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


def update_symbol_icons(user_id, dream_id, symbols, symbol_icons):
    """
    Overwrite just a dream's symbols and symbol_icons columns, leaving
    everything else (text, themes, people, settings, interpretation,
    embedding, conversation) untouched. Used by backfill_symbol_icons.py
    to fill in icon data for dreams logged before that column existed --
    update_dream() would also wipe the conversation and re-run the full
    interpretation, which is overkill (and risky, since it'd also drift
    the reading itself) just to add icons. symbols is passed alongside
    symbol_icons, not left as-is, because they come from the same fresh
    extraction call and symbol_icons' keys need to match it exactly --
    writing one without the other risks a dangling icon that doesn't
    match any symbol actually stored.
    """
    _execute(
        "UPDATE dreams SET symbols = ?, symbol_icons = ? WHERE id = ? AND user_id = ?",
        (
            json.dumps(symbols, ensure_ascii=False),
            json.dumps(symbol_icons, ensure_ascii=False),
            dream_id,
            user_id,
        )
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
        "location": row["location"] or "",
        "symbol_icons": json.loads(row["symbol_icons"] or "{}"),
        "emotions_reported": json.loads(row["emotions_reported"] or "[]"),
        "emotions_plutchik": json.loads(row["emotions_plutchik"] or "[]"),
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


def get_dream_ids(user_id):
    """Just the ids of every dream this user has, cheapest possible query
    for it -- used by account deletion to know which vectorstore entries
    to clean up before the rows they describe are gone."""
    rows, _ = _execute("SELECT id FROM dreams WHERE user_id = ?", (user_id,))
    return [row[0] for row in rows]




def delete_account(user_id):
    """
    Permanently erase one account and everything that belongs to it:
    every dream, the profile row, every symbol-chat thread, and the user
    row itself. No undo -- the caller (main.py's DELETE /account) is
    where any "are you sure" step belongs, not here.

    Deliberately separate DELETEs rather than relying on a foreign key
    ON DELETE CASCADE: this schema was never declared with FK
    constraints (see init_db -- dreams.user_id, profile.user_id, and
    symbol_chats.user_id are plain INTEGER columns), and Turso/libsql
    don't enforce them retroactively, so cascading only happens if this
    function actually does it.

    Order matters only in that the user row goes last -- if anything
    above raised partway through, the account would still be reachable
    by its login token rather than half-erased but unrecoverable.
    """
    _execute("DELETE FROM dreams WHERE user_id = ?", (user_id,))
    _execute("DELETE FROM profile WHERE user_id = ?", (user_id,))
    _execute("DELETE FROM symbol_chats WHERE user_id = ?", (user_id,))
    _execute("DELETE FROM personal_meanings WHERE user_id = ?", (user_id,))
    _execute("DELETE FROM connection_feedback WHERE user_id = ?", (user_id,))
    _execute("DELETE FROM users WHERE id = ?", (user_id,))


# --- Symbol chats: one conversation thread per (user, symbol) --------------

def get_symbol_conversation(user_id, symbol_key):
    """The conversation so far for this user's thread on one symbol, or
    [] if they've never opened it."""
    rows, _ = _execute(
        "SELECT conversation FROM symbol_chats WHERE user_id = ? AND symbol_key = ?",
        (user_id, symbol_key),
    )
    if not rows:
        return []
    return json.loads(rows[0]["conversation"] or "[]")


def update_symbol_conversation(user_id, symbol_key, symbol_label, messages):
    """
    Save the ongoing conversation about one symbol. INSERT OR REPLACE
    since there's exactly one row per (user_id, symbol_key) -- same
    reasoning as save_profile above. symbol_label is rewritten on every
    save too, so the thread always remembers the most recently-seen real
    casing for display even if an older dream used different casing for
    the same normalized symbol.
    """
    _execute("""
        INSERT OR REPLACE INTO symbol_chats (user_id, symbol_key, symbol_label, conversation)
        VALUES (?, ?, ?, ?)
    """, (user_id, symbol_key, symbol_label, json.dumps(messages, ensure_ascii=False)))


# --- Personal meanings: what a symbol/emotion/person/place means to THIS
# user, entirely separate from anything AI-generated (see the brief's
# Personal Meaning section, and init_db's comment above for why this
# table exists at all) ------------------------------------------------------

def list_personal_meanings(user_id):
    """Every personal meaning this user has saved, most recently updated
    first -- the shape a Loom Map or Settings overview would want to
    render a full list from."""
    rows, _ = _execute(
        "SELECT * FROM personal_meanings WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,),
    )
    return [_row_to_dict(row) for row in rows]


def get_personal_meaning(user_id, subject_type, subject_key):
    """This user's personal meaning for one subject, or None if they've
    never recorded one."""
    rows, _ = _execute(
        "SELECT * FROM personal_meanings WHERE user_id = ? AND subject_type = ? AND subject_key = ?",
        (user_id, subject_type, subject_key),
    )
    return _row_to_dict(rows[0]) if rows else None


def save_personal_meaning(user_id, subject_type, subject_key, subject_label, meaning, note=""):
    """
    Create or update this user's personal meaning for one subject.
    INSERT OR REPLACE since there's exactly one row per (user_id,
    subject_type, subject_key) -- same reasoning as save_profile/
    update_symbol_conversation above. created_at is preserved across an
    edit (re-read from any existing row) so "added on" stays accurate
    even though updated_at moves forward on every save.
    """
    existing = get_personal_meaning(user_id, subject_type, subject_key)
    now = datetime.now().isoformat()
    created_at = existing["created_at"] if existing else now
    _execute("""
        INSERT OR REPLACE INTO personal_meanings
            (user_id, subject_type, subject_key, subject_label, meaning, note, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, subject_type, subject_key, subject_label, meaning, note or "", created_at, now))
    return get_personal_meaning(user_id, subject_type, subject_key)


def delete_personal_meaning(user_id, subject_type, subject_key):
    _execute(
        "DELETE FROM personal_meanings WHERE user_id = ? AND subject_type = ? AND subject_key = ?",
        (user_id, subject_type, subject_key),
    )


# --- Connection feedback: "relevant" / "not relevant" / "confirmed" on a
# suggested connection or a Discoveries card -------------------------------
#
# This is explicit user data, recorded because the brief asks feedback to
# be captured even where persistent learning isn't implemented yet -- it
# does NOT retrain or otherwise alter engine.py's output. Nothing in this
# file should be read as implying otherwise; if that ever changes, say so
# here and wherever this table is surfaced in the UI.

def list_connection_feedback(user_id):
    rows, _ = _execute(
        "SELECT * FROM connection_feedback WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,),
    )
    return [_row_to_dict(row) for row in rows]


def get_connection_feedback(user_id, connection_key):
    rows, _ = _execute(
        "SELECT * FROM connection_feedback WHERE user_id = ? AND connection_key = ?",
        (user_id, connection_key),
    )
    return _row_to_dict(rows[0]) if rows else None


def save_connection_feedback(user_id, connection_key, status, note=""):
    """
    Record this user's feedback on one connection or discovery.
    INSERT OR REPLACE since there's exactly one row per (user_id,
    connection_key) -- a second click just updates the status (e.g.
    "relevant" changed to "not relevant") rather than piling up a
    history of every click.
    """
    existing = get_connection_feedback(user_id, connection_key)
    now = datetime.now().isoformat()
    created_at = existing["created_at"] if existing else now
    _execute("""
        INSERT OR REPLACE INTO connection_feedback
            (user_id, connection_key, status, note, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, connection_key, status, note or "", created_at, now))
    return get_connection_feedback(user_id, connection_key)
