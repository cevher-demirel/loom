# Stage 25 -- dream loading reliability

Incident: GET /dreams returned 500 on Turso (dict(row) on libsql rows, fixed in #51), and the app showed "Nothing logged yet" because a failed load left the pre-load empty state in place.

Changes
- Frontend: explicit loading / loaded / error states for the dream list, a persistent banner with Retry, concurrent loads share one request, 60s timeout, auto-retry on the browser's online event. A failed refresh never replaces an already-loaded list. A genuinely empty account still shows the empty state.
- Backend: GET /dreams has no fallback. If the confirmations overlay fails, the failure is logged (event entity_confirmations_failed, error type/message only, no dream text) and re-raised, so the request is a real 500.

PR #50 decision: its frontend changes were kept (rebuilt on current main). Its backend try/except fallback that returned dreams without the overlay was rejected because it hid failures and returned incomplete data.

No schema changes, no migrations, no data writes.
