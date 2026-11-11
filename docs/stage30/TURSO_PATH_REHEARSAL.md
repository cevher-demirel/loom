# Turso code-path and migration rehearsal (local, synthetic data, no Turso account touched)

Nothing here touched the production Turso database, any real user data, the encrypted backup, Render, Cloudflare or Google. I had no Turso access and used none.

## What was run and how
Every automated test before this ran on SQLite only. The app talks to Turso through `libsql_client` (HTTP). To test that exact path without Turso, a **libSQL server (`sqld` 0.24.32, the open-source engine Turso is built on) ran on this machine only**, installed from npm into a scratch folder with install scripts disabled. It is a stand-in for Turso, not Turso itself.
1. **Test suite through the Turso client path.** `LOOM_LIBSQL_TEST_URL=http://127.0.0.1:<port>` makes the shared `fresh_db` fixture use `libsql_client` against that server (opt-in; refuses any non-local address; the existing production-credential guard is unchanged; off by default and in CI). Result: **422 passed, 1 skipped** across database, OAuth (including one-time ticket/flow claims `DELETE … RETURNING`, replay, concurrent account creation/linking, Google-only account deletion with reauthentication), the API, and the legacy-data tests. The 1 skip is the test that asserts "no Turso is used".
2. **Migration rehearsal** (`scripts/migration_rehearsal.py`): the OLD production code (`166ac63`'s `database.py`) created the old schema and **65 synthetic accounts, 183 synthetic dreams, 40 profiles** on a fresh server; the NEW code then migrated it three times (as three restarts). Result: existing tables **byte-identical** (row count + SHA-256 of every row + column list); only the three new tables appear (empty); repeating the migration changes nothing; all 65 old accounts still authenticate; real `/login` and `/dreams` return the right counts; Google identities link only under the rules (linked / already / conflict), an identity cannot attach to a second account, one account cannot get a second identity; a new Google account was created → 66 users, 183 dreams. **PASS.**
3. **Safety of the rehearsal tool:** refuses any target except this machine or a Turso database whose name starts with `loom-rehearsal`; production (`loom`) is refused; tested.

## Bugs found and fixed
| Bug | Where | Impact |
|---|---|---|
| Google email lookup compared stored email case-sensitively | `database.find_user_by_email` (new Stage 30 code) | A legacy account whose stored email had capitals would NOT be offered linking: Google sign-in created a second account. Now `LOWER(email)`; regression test added; it fails without the fix |
| Tests assumed SQLite row objects (`dict(row)`) | tests only | Made backend-neutral |
No application bug was found in the Turso client path itself.

## What this does NOT prove
It is not Turso: network latency, Turso's hosted behaviour, tokens and plan limits are untested. Real Google was not involved. Remaining ways to close the gap (owner choice): create a scratch Turso database named `loom-rehearsal-…` and run `scripts/migration_rehearsal.py --url <its libsql URL> --allow-remote-scratch` from your own shell with that database's token (synthetic data only); and run `scripts/migrate_copy_check.py` on a COPY of the real backup (below).

## Owner-run check on the real backup (data never leaves your PC)
Mount the encrypted container yourself, then in PowerShell from a checkout of this branch:
`python scripts\migrate_copy_check.py --db "<path to the exported .db>"` (keep the `.db-wal` file next to it).
It copies the files to a temporary folder, migrates the COPY three times, compares every existing table before/after, and prints only counts, hashes and yes/no results (including how many emails contain capitals). It proves the original files are unchanged by hashing them before and after, then deletes its copy. Tested on a synthetic WAL-mode backup. Expected: `RESULT: PASS`, accounts 65 -> 65, dreams 183 -> 183.
