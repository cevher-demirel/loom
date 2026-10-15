"""
backfill_pinecone.py -- one-time script to push every existing dream's
already-computed embedding (sitting in Turso) into Pinecone.

Why this exists: vectorstore.upsert_dream() only gets called from
main.py when a dream is freshly logged (POST /interpret) or edited
(PUT /dreams/{id}). Any dream that already existed before Pinecone was
wired in has an embedding stored in Turso, but Pinecone has never seen
it -- so similarity search would silently find nothing for it until it's
either edited (which re-embeds and re-upserts automatically) or
backfilled here, once, by hand.

IMPORTANT: this needs to run against the REAL production database, not
a local fallback one -- make sure your .env has TURSO_DATABASE_URL and
TURSO_AUTH_TOKEN set (the same values Render uses) before running this,
or it'll happily connect to an empty local loom.db instead and find
nothing to backfill.

Run it once, after PINECONE_API_KEY (and TURSO_DATABASE_URL/
TURSO_AUTH_TOKEN) are set, with:
    python backfill_pinecone.py

Safe to run more than once -- upsert_dream() overwrites by the same
vector id rather than creating duplicates, so re-running this just
re-sends the same vectors.
"""

import database
import vectorstore


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
    total_skipped_no_embedding = 0

    for row in rows:
        user_id = row["id"]
        username = row["username"]
        dreams = database.get_all_dreams(user_id)
        total_dreams += len(dreams)
        for dream in dreams:
            if not dream["embedding"]:
                # Pre-Voyage dreams (old word-list "embeddings") or a
                # dream whose embedding call failed at the time -- nothing
                # real to upsert. These start participating in similarity
                # search once re-interpreted (see engine.find_similar_dreams'
                # own docstring for the same situation).
                total_skipped_no_embedding += 1
                continue
            vectorstore.upsert_dream(user_id, dream["id"], dream["embedding"])
            total_upserted += 1
        print(f"  {username}: {len(dreams)} dream(s) processed")

    print()
    print(f"Done. {total_users} user(s), {total_dreams} dream(s) total, "
          f"{total_upserted} upserted into Pinecone, "
          f"{total_skipped_no_embedding} skipped (no usable embedding).")


if __name__ == "__main__":
    run()
