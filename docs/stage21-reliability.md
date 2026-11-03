# Stage 21 — duplicate-safe dream submission

## What is guaranteed
`POST /interpret` accepts an optional `request_id` (8–100 chars, `[A-Za-z0-9_-]`).
For an authenticated user, **at most one dream is ever saved per `request_id`**:

* enforced by the database — `UNIQUE INDEX idx_dreams_user_request ON dreams(user_id, request_id)`
  and the `PRIMARY KEY (user_id, request_id)` of `dream_submissions` (the atomic claim);
* scoped by the authenticated user id, so ids never collide or leak between accounts;
* same id + different content (text, date, place, emotions) → `409 idempotency_conflict`;
* same id while another attempt is running → `409 in_progress` (no AI call, no rate-limit budget used);
* same id after completion → the stored result is replayed (no AI call, no new row, no budget used);
* if the dream was deleted since, a replay answers `409 already_deleted` (never resurrected);
* a failed attempt (AI error, extraction error, rate limit, client disconnect) releases its claim so a retry runs normally;
* a crashed attempt (server died) is taken over after 300 s (`SUBMISSION_STALE_SECONDS`) by compare-and-swap on an owner token, so the dead owner can never finish it afterwards; a crash *after* the dream row was written replays from that row;
* requests without `request_id` (older clients) behave exactly as before.

Not claimed: exactly-once *AI execution* across a server crash mid-stream — a taken-over submission re-runs the AI once; it still saves at most one dream.

## Migration (runs automatically in `init_db()` at start-up)
Purely additive and idempotent (safe to run repeatedly):

```sql
ALTER TABLE dreams ADD COLUMN request_id TEXT;                       -- NULL for every existing row
CREATE UNIQUE INDEX IF NOT EXISTS idx_dreams_user_request ON dreams(user_id, request_id);
CREATE TABLE IF NOT EXISTS dream_submissions (...);
```
NULLs never collide in a UNIQUE index, so existing dreams and old clients are untouched. No row is rewritten or deleted.

### Rollback
Application rollback needs no DB action: the old code ignores the extra column/table.
To remove the feature entirely (optional, destructive only to coordination data):
```sql
DROP INDEX IF EXISTS idx_dreams_user_request;
DROP TABLE IF EXISTS dream_submissions;
-- dreams.request_id may stay (harmless nullable column); SQLite/libSQL can DROP COLUMN if desired.
```

## Deploy order and compatibility
1. Merge to `main`: Render builds the backend (runs the migration on boot); GitHub Pages publishes `index.html`.
2. Check `GET https://loom-phas.onrender.com/health` → `"features": ["idempotent_interpret"]`.
3. Old page + new backend: works (no `request_id`, legacy behaviour).
4. New page + old backend (Pages finishing before Render): the page reads `/health`; without the feature flag it **never auto-resends** and says "Your dream may have been saved. Check your Journal before trying again."

## Manual production smoke (cannot be run from CI/sandbox)
1. Open the site, log in with a throw-away account, record a short dream, pick one emotion, **Add to Dream** → Dream Detail opens; Journal shows exactly one new dream.
2. DevTools → Network → set *Offline* right after pressing Add to Dream, wait ~10 s, go *Online*: the page keeps checking and lands on the saved dream; Journal still shows one.
3. Re-run step 1 with identical text twice in two tabs quickly: only one dream appears.
4. Confirm `/health` features and that the existing account's old dreams still open (Journal, Dream Detail, Loom Map, Insights).
