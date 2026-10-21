"""
backfill_symbol_icons.py -- one-time script to fill in symbol_icons for
every existing dream that doesn't have it yet.

Why this exists: the symbol_icons column (a {symbol text: icon category}
map used by the swipeable Symbols card row -- see engine.ICON_CATEGORIES
and index.html's ICON_SVGS) only gets populated for a dream freshly
logged (POST /interpret) or edited (PUT /dreams/{id}), both of which run
engine.extract_dream_data(). Any dream that already existed before this
column was added has symbol_icons = NULL, which reads back as {} -- so
its Symbols row is just empty, even though the dream, its interpretation,
and its conversation are all otherwise fine.

This re-runs extraction on each such dream's existing raw_text and saves
only the resulting symbols + symbol_icons back (via
database.update_symbol_icons), never touching interpretation, themes,
people, settings, embedding, or conversation. The re-extracted "symbols"
list may differ slightly in wording from what the dream's original
interpretation text happens to reference (e.g. "a locked door" vs "the
locked door") -- cosmetic, and not worth avoiding by trying to preserve
the old symbols list, since symbol_icons' keys have to exactly match
whatever symbols list ships with it.

IMPORTANT: this needs to run against the REAL production database, not
a local fallback one -- make sure your .env has TURSO_DATABASE_URL and
TURSO_AUTH_TOKEN set (the same values Render uses) before running this,
or it'll happily connect to an empty local loom.db instead and find
nothing to backfill.

Run it once, after TURSO_DATABASE_URL/TURSO_AUTH_TOKEN are set, with:
    python backfill_symbol_icons.py

Safe to run more than once -- by default, a dream that already has at
least one entry in symbol_icons is skipped, so re-running this only
picks up whatever's still missing (e.g. a dream whose extraction call
failed on a previous run).

Pass --force to re-extract EVERY dream instead, overwriting whatever
symbol_icons it already has. Useful after ICON_CATEGORIES gains a new
category (like "screen", added for laptops/monitors/phones-on-screen)
or the classification prompt changes meaningfully -- without --force,
a dream already backfilled under an older category list keeps whatever
it got then, even if a newer category would now fit it better. The
model's category pick for a borderline symbol isn't perfectly
deterministic either, so --force can also just pick a better match on
a second try for something that was already in reasonable range:
    python backfill_symbol_icons.py --force
"""

import sys
import time

import database
import engine


def run():
    force = "--force" in sys.argv[1:]
    # Same startup step main.py does on import -- creates the local
    # tables if this ever does fall back to local SQLite, and is a
    # harmless no-op against Turso if everything already exists there.
    database.init_db()

    if not database.USE_TURSO:
        print("WARNING: TURSO_DATABASE_URL isn't set in .env -- this would run against "
              "an empty local database instead of your real production data. "
              "Add TURSO_DATABASE_URL and TURSO_AUTH_TOKEN to .env (same values Render "
              "uses) and try again.")
        return

    # database.py scopes everything by user_id on purpose -- there's no
    # "every dream, every user" query built in, since nothing in the app
    # ever needs to cross that boundary except a one-time maintenance
    # script like this one. Going straight at the users table here is
    # the one deliberate exception.
    rows, _ = database._execute("SELECT id, username FROM users")

    total_users = len(rows)
    total_dreams = 0
    total_backfilled = 0
    total_skipped_already_has_icons = 0
    total_skipped_no_symbols_found = 0
    total_failed = 0

    for row in rows:
        user_id = row["id"]
        username = row["username"]
        dreams = database.get_all_dreams(user_id)
        total_dreams += len(dreams)
        backfilled_for_user = 0
        for dream in dreams:
            if dream["symbol_icons"] and not force:
                total_skipped_already_has_icons += 1
                continue
            try:
                extracted = engine.extract_dream_data(dream["raw_text"])
            except Exception as e:
                print(f"  {username} dream {dream['id']}: extraction failed ({e}), skipping")
                total_failed += 1
                continue
            symbols = extracted.get("symbols", [])
            symbol_icons = extracted.get("symbol_icons", {})
            if not symbols or not symbol_icons:
                # Nothing genuinely concrete in this dream, or nothing
                # that matched a real icon category -- leave it as an
                # empty Symbols row rather than writing an empty update.
                total_skipped_no_symbols_found += 1
                continue
            database.update_symbol_icons(user_id, dream["id"], symbols, symbol_icons)
            backfilled_for_user += 1
            total_backfilled += 1
            time.sleep(0.5)  # same pacing as backfill_pinecone.py, same reason: avoid rate limits
        if backfilled_for_user:
            print(f"  {username}: {backfilled_for_user} dream(s) backfilled")

    print()
    print(f"Done. {total_users} user(s), {total_dreams} dream(s) total, "
          f"{total_backfilled} backfilled, "
          f"{total_skipped_already_has_icons} already had icons, "
          f"{total_skipped_no_symbols_found} had no symbol that got a real icon, "
          f"{total_failed} failed (try running again).")


if __name__ == "__main__":
    run()
