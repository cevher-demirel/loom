# Migration safety (Stage 29 schema changes)

All results below are from **synthetic** databases. Nothing was run against production.

## What the migration does (`database.init_db`, runs at every start)
Additive only, each step idempotent:
- `CREATE TABLE IF NOT EXISTS` for `auth_identities` (`UNIQUE(provider, subject)`), `oauth_flows`, `oauth_tickets`.
- `ALTER TABLE oauth_flows ADD COLUMN` `binding_hash`, `purpose` (default `'login'`), `user_id`, each only if absent.
- `CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_identities_user_provider ON auth_identities (user_id, provider)`.
No row in `users`, `dreams` or any existing table is read for rewriting, updated or deleted. No foreign keys are declared anywhere, so cleanup on deletion is done in code (`delete_account`).

## Changes made in Stage 30
1. **Index creation can no longer take the API down.** If pre-existing duplicate `(user_id, provider)` rows make the unique index impossible, `init_db` logs `schema_warning` (counts and the exception *type* only, no personal data), skips the index and starts normally. Previously it would have raised and the backend would not boot.
2. **`link_identity_safely` checks the per-account rule itself**, so "one Google identity per account" holds even when the index could not be created. On a healthy database the index still makes it race-proof.
3. `database.auth_identity_conflicts()` and `scripts/preflight_auth_identities.py`: read-only conflict report, counts only.

## Synthetic databases and results (`tests/test_migration_safety.py`, 9 tests, all pass)
Schemas come from `tests/fixtures/schema_stage27d.sql` and `schema_stage28.sql`, dumped from the real historical `database.py` (commits `f238114` and `e9a7a27`).
| # | Scenario | Result |
|---|---|---|
| 1 | Clean install | All tables/columns/index created; running `init_db` three times leaves an identical schema |
| 2 | Existing install without OAuth (Stage 27d schema; 4 users, 12 dreams) | Same user IDs, emails, password hashes and dreams after migration; email/password sign-in still works; wrong password still fails; second run changes nothing |
| 3 | Existing linked Google identities (Stage 28 schema) | Identities untouched; the same identity cannot attach to a second account; a second identity cannot attach to the same account |
| 4 | Duplicate provider identities for one account | Startup does not fail; rows are not merged, deleted or rewritten; index is skipped with a counts-only warning; the app still refuses another link; the preflight exits 1, prints counts only, and the database file is **byte-for-byte unchanged** |
| 5 | Interrupted/failed migration | A simulated crash injected at **every** statement of `init_db` (one run per statement): users and dreams are identical afterwards, and the next start completes the schema |
| 6 | Several users with dreams | Deleting one account removes only that user's dreams and identity; the others are intact; no foreign keys exist |
Concurrent account creation and concurrent linking are covered in `tests/test_oauth.py` (many threads, one resulting account/identity).

## Production preflight (read-only; NOT run in this stage)
For an authorised operator, ideally against a copy or a Turso branch/restore first:
```bash
python scripts/preflight_auth_identities.py --db path/to/copy.db
# later, only if the operator chooses, against the configured backend (their own shell holds the credentials):
python scripts/preflight_auth_identities.py --configured-backend --i-am-the-operator
```
It issues `SELECT` statements only (any other statement is refused in code), never calls `init_db`, never migrates, and prints counts such as `identities_total`, `duplicate_user_provider_groups`, `duplicate_provider_subject_groups`, `orphan_identities_without_user`, `unique_index_present`, `users_total`. Exit 0 = no conflicts; 1 = conflicts; 2 = refused or bad usage.
Note: Stage 28/29 have never been deployed, so production most likely has no `auth_identities` table yet (the preflight then reports that the migration will create it empty). This is an expectation, not a verified fact.

## Remediation if conflicts are ever found
Do not auto-merge. For each duplicate group the operator decides, with the affected person if needed, which identity is the real one; remove the other rows by hand with a reviewed, logged statement; re-run the preflight; restart so `init_db` creates the index. Duplicate `(provider, subject)` groups cannot exist while the older `UNIQUE` constraint is present.
