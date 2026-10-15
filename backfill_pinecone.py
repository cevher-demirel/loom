"""
backfill_pinecone.py -- one-time script to push every existing dream's
embedding into Pinecone, regenerating it first for any dream that
doesn't actually have a real one yet.

Why this exists: vectorstore.upsert_dream() only gets called from
main.py when a dream is freshly logged (POST /interpret) or edited
(PUT /dreams/{id}). Any dream that already existed before Pinecone was
wired in has... something in its embedding column in Turso, but
Pinecone has never seen it -- so similarity search would silently find
nothing for it until it's either edited (which re-embeds and re-upserts
automatically) or backfilled here, once, by hand.

That "something" isn't always a real embedding, either. Loom's embedding
column predates Voyage AI -- it used to hold a word-overlap fingerprint
(a plain list of significant words, e.g. ["boat", "captain",
"unconscious"]), not a numeric vector. Any dream logged before the
Voyage AI switch still has that old word-list sitting in the column,
and Pinecone rejects it outright (it needs floats, not strings). This
script treats that the same as a missing embedding: it re-embeds the
dream's actual text through Voyage AI right here, saves the real vector
back to Turso (so this is also a one-time fix, not just a workaround),
and then upserts it.

IMPORTANT: this needs to run against the REAL production database, not
a local fallback one -- make sure your .env has TURSO_DATABASE_URL and
TURSO_AUTH_TOKEN set (the same values Render uses) before running this,
or it'll happily connect to an empty local loom.db instead and find
nothing to backfill.

Run it once, after PINECONE_API_KEY (and TURSO_DATABASE_URL/
TURSO_AUTH_TOKEN) are set, with:
    python backfill_pinecone.py

Safe to run more than once -- upsert_dream() overwrites by the same
vector id rather than creating duplicates, and a dream that already has
a real embedding won't be re-embedded again, so re-running this just
re-sends the same vectors and costs nothing extra.
"""

import database
import engine
import vectorstore


def _is_real_embedding(embedding):
    """
    True only for an actual numeric vector -- a non-empty list where
    every entry is an int or float. False for an empty list (embed call
    failed or never ran) and false for the old word-overlap fingerprint
    (a list of strings), which is exactly the distinction this script
    needs to decide whether a dream needs re-embedding.
    """
    if not embedding:
        return False
    return all(isinstance(v, (int, float)) for v in embedding)


def run():
    # Same startup step main.py does on import -- creates the local
    # tables if this ever does fall back to local SQLite, and is a
    # harmless no-op against Turso if everything already exists there.
    database.init_db()

    if not vectorstore.is_configured():
        print("PINECONE_API_KEY isn't set -- nothing to backfill. Add it to .env first.")
        return

    if not database.USE_TURSO:
        print("WARNING: TURSO_DATABASE_URL isn't set in .env -- this would run against "
              "an empty local database instead of your real production data. "
              "Add TURSO_DATABASE_URL and TURSO_AUTH_TOKEN to .env (same values Render "
              "uses) and try again.")
        return

    # database.py scopes everything by user_id on purpose -- there's no
    # "every dream, every user" query built in, since nothing in the app
    # ever needs to cross that boundary except this one maintenance
    # script. Going straight at the users table here is the one
    # deliberate exception.
    rows, _ = database._execute("SELECT id, username FROM users")

    total_users = len(rows)
    total_dreams = 0
    total_upserted = 0
    total_reembedded = 0
    total_skipped_still_empty = 0

    for row in rows:
        user_id = row["id"]
        username = row["username"]
        dreams = database.get_all_dreams(user_id)
        total_dreams += len(dreams)
        for dream in dreams:
            embedding = dream["embedding"]
            if not _is_real_embedding(embedding):
                # Old word-overlap fingerprint, or a never-succeeded
                # embed call -- regenerate from the dream's actual text
                # rather than skipping it.
                embedding = engine.embed_text(dream["raw_text"], input_type="document")
                if not embedding:
                    # Voyage call itself failed just now -- nothing to
                    # upsert this time, try again on a future run.
                    total_skipped_still_empty += 1
                    continue
                database.update_embedding(user_id, dream["id"], embedding)
                total_reembedded += 1
            vectorstore.upsert_dream(user_id, dream["id"], embedding)
            total_upserted += 1
        print(f"  {username}: {len(dreams)} dream(s) processed")

    print()
    print(f"Done. {total_users} user(s), {total_dreams} dream(s) total, "
          f"{total_upserted} upserted into Pinecone "
          f"({total_reembedded} of those needed re-embedding first), "
          f"{total_skipped_still_empty} skipped (embedding call failed just now).")


if __name__ == "__main__":
    run()
