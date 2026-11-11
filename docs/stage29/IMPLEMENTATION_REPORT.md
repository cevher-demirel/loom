# Stage 29 — Implementation report

Branch `stage-29-oauth-security` (from `e9a7a27`). Local only.

## Files
| File | Change |
|---|---|
| `oauth.py` | Browser binding, PKCE, OIDC validation, config validation, `complete_sign_in` (login / link / reauth), startup report |
| `main.py` | Auth routes (start/callback/exchange/link/providers), `POST /account/reauth/{provider}`, new `DELETE /account` body, access-log redaction, rate limits, `AccountOut.has_password/google_linked` |
| `database.py` | Additive schema (below), atomic pop helpers, race-safe identity/user creation, deletion cleans identities/tickets/flows |
| `index.html` | Minimal deletion UI and return handling only. Login design untouched |
| `tests/mock_idp.py` | Local HTTP OIDC provider for tests (PKCE, single-use codes, RS256 + JWKS) |
| `tests/test_oauth.py` | 66 tests |
| `tests/browser/test_stage29_google_e2e.py` | 6 tests: real page + real FastAPI + mock IdP |

## Database changes (additive only; `init_db` runs `ALTER … ADD COLUMN` / `CREATE … IF NOT EXISTS`)
- `oauth_flows`: `binding_hash TEXT`, `purpose TEXT NOT NULL DEFAULT 'login'`, `user_id INTEGER`.
- Unique index `idx_auth_identities_user_provider (user_id, provider)`. Existing `UNIQUE(provider, subject)` stays.
- No data is rewritten or deleted. If production already has two identities for one user/provider, index creation would fail: check that before release.

## Flow
1. `GET /auth/google/start` creates state, nonce, PKCE verifier and a random binding secret. Stores them (secret only as SHA-256), sets cookie `loom_oauth_<hash(state)[:16]>`: HttpOnly, `Path=/auth`, 10 min, `Secure` on https, **SameSite=Lax**, then 303 to Google.
2. Callback atomically consumes the flow, checks provider, 10-min expiry and cookie, exchanges the code with the verifier, verifies the id_token, then clears the cookie. Any failure burns the flow.
3. Result: login ticket (new/known identity), link ticket (verified email matches an existing password account), or reauth ticket. The browser returns to `FRONTEND_URL/#…`; the frontend exchanges the ticket via `POST /auth/exchange`.

**Why Lax, not Strict:** Google returns via a cross-site top-level GET. Strict would drop the cookie and break every legitimate login; Lax sends it on that navigation but not on cross-site forms or subrequests. A cookie per flow keeps parallel tabs from clobbering each other.

## Account protection
Identity lookup is by `sub` first. Email is used only to *offer* linking, and linking needs the existing account's password (5 wrong tries burn the ticket). Unverified emails are refused. A second Google identity cannot attach to an account that already has one. Changed email at Google does not matter: the `sub` still matches. Cancelled or failed links leave no row.

## Deletion
- Password account: unchanged (`{password}`).
- Google-linked account: the user clicks **Verify with Google** → `POST /account/reauth/google` (authenticated) returns a one-use URL → Google is asked with `prompt=login&max_age=0` → callback requires the returned `sub` to equal the identity linked to that user (`reauth_mismatch` otherwise) → page returns with a 5-minute single-use ticket in the fragment, held only in memory → the user must click a separate **Permanently delete my account** → `DELETE /account {reauth_ticket}` consumes it atomically.
- Accounts with both methods see both options. Unlinking is never substituted for deletion.
- Deletion removes dreams, profile data, sessions, identities, tickets, flows (existing semantics plus the V6 fix). The UI states it is permanent.
- Cancel at Google, mismatch, expiry, replay and other-browser attempts all leave the account intact (tested).

## Design decisions
Minimal UI change: one extra block inside the existing danger-zone panel; all Stage 28 IDs and visuals kept; no Apple in the UI. `DELETE` uses plain `fetch` so a refused confirmation shows its own message instead of the session-expired handler.
