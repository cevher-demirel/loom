"""
Database layer for Loom.

Stores every logged dream, plus the structured data extracted from it
(symbols, emotions, people, settings, themes) and its semantic embedding,
in a local SQLite database. SQLite is a lightweight, file-based database --
no server to install or run, just a single .db file sitting in this folder.
"""

import sqlite3
import json
from datetime import datetime

DB_PATH = "loom.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    """Create the dreams table if it doesn't already exist. Safe to call
    every time the app starts -- it only creates the table once."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dreams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    # Migration: if you already have a loom.db from before this feature
    # existed, add the new column without losing any of your existing
    # dreams. ALTER TABLE fails harmlessly if the column already exists.
    try:
        cur.execute("ALTER TABLE dreams ADD COLUMN conversation TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists -- nothing to do

    # Profile table -- a single row (id is always 1) holding the person's
    # info: who they are, where they're from, where they are now, and a
    # free-text bio. This gets woven into interpretation prompts so
    # readings are grounded in the person's actual life, not generic.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
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


def get_profile():
    """Return the person's profile as a dict, or an empty-but-valid dict
    if they haven't filled one in yet."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM profile WHERE id = 1")
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


def save_profile(data):
    """
    Save the person's profile. `data` is a dict with keys name, birth_year,
    birthplace, current_location, bio, picture_path -- any missing key is
    treated as empty. Uses INSERT OR REPLACE since there's only ever one
    profile row (id=1).
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO profile
            (id, name, birth_year, birthplace, current_location, bio, picture_path)
        VALUES (1, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("name", ""),
        data.get("birth_year"),
        data.get("birthplace", ""),
        data.get("current_location", ""),
        data.get("bio", ""),
        data.get("picture_path", ""),
    ))
    conn.commit()
    conn.close()


def insert_dream(raw_text, extracted, interpretation, embedding):
    """
    Save a new dream to the database.

    extracted: dict with keys symbols, emotions, people, settings, themes
               (each a list of strings) -- these get stored as JSON text,
               since SQLite doesn't have a native "list" column type.
    embedding: list of floats (the dream's semantic vector), also stored
               as JSON text.

    Returns the new dream's id.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO dreams (timestamp, raw_text, symbols, emotions, people,
                             settings, themes, interpretation, embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
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


def update_dream_conversation(dream_id, messages):
    """
    Save the ongoing conversation about a specific dream -- every follow-up
    question and answer after the initial interpretation. Called again
    each time the conversation continues, so it always stores the full
    thread so far.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE dreams SET conversation = ? WHERE id = ?",
        (json.dumps(messages, ensure_ascii=False), dream_id)
    )
    conn.commit()
    conn.close()


def get_all_dreams():
    """Return every stored dream, oldest first, as a list of dicts with
    the JSON fields already parsed back into real Python lists."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM dreams ORDER BY timestamp ASC")
    rows = cur.fetchall()
    conn.close()

    dreams = []
    for row in rows:
        dreams.append({
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
            "conversation": json.loads(row["conversation"] or "[]") if "conversation" in row.keys() else [],
        })
    return dreams


def count_dreams():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM dreams")
    count = cur.fetchone()[0]
    conn.close()
    return count
