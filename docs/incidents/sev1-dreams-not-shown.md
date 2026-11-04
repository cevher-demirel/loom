# SEV-1: dreams not shown after refresh

Finding (read-only): backend /health ok (database ok); /dreams returns 200. No data was modified.
Defect: the app painted "Nothing logged yet" at boot and, if GET /dreams then failed (timeout, cold start, 5xx), showed only a transient toast and left the empty state, so a failed load looked like an empty journal.
Fix: explicit loading / loaded / error states with a persistent banner and Retry; a failed refresh never clears a loaded list; concurrent refreshes share one request; 60s timeout; auto-retry when the browser comes back online. Backend: the optional entity_confirmations overlay can no longer fail /dreams.
