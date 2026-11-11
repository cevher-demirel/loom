# Stage 28 — Authentication audit

Audit of the existing auth, done by reading code only (no production access, no live requests).

## How sign-in works today
- `users` table: `username` (unique), `email`, `password_hash`, `salt`, `token`, `token_created_at`, plus reset/verify token columns.
- Passwords: PBKDF2-HMAC-SHA256, 200,000 iterations, random per-user salt.
- Session: one random 64-hex token per user, sent as `Authorization: Bearer`, stored by the browser in `localStorage`. 30-day lifetime. Every login issues a new token (signing in elsewhere signs the other device out). `/logout` clears it.
- Login field takes a username **or** an email. Signup needs username, email and a password (8+ chars, a letter, a digit, not a common password).
- Reset: emailed one-hour token; `/forgot-password` always answers `{"ok": true}`.
- Rate limits (in memory, per IP): signup 10/h, login 15/15 min, forgot 5/h.
- Dreams, Loom Map data and profile are keyed by `user_id`. Nothing in them depends on how the person signs in.

## Risks found
| # | Finding | Status in this change |
|---|---|---|
| 1 | A username could equal someone else's email, and login picked the first matching row. | **Fixed.** Login now tests every match and accepts the one whose password verifies. New usernames can't contain `@`. Existing accounts are untouched and still sign in. |
| 2 | Password comparison used `!=`. | **Fixed** (`hmac.compare_digest`). |
| 3 | PBKDF2 at 200k iterations is below current OWASP guidance. | Not changed. Recommended follow-up: re-hash at login with a higher count. |
| 4 | Session tokens stored unhashed; one session per account; token in `localStorage`; no MFA; in-memory rate limits reset on restart. | Not changed. Follow-ups. |
| 5 | Account deletion requires the password. A provider-only account has none. | **Gate before enabling Google/Apple in production.** Interim path: such accounts that have a verified email can use "Forgot password" to set one, then delete. Apple requires in-app account deletion for apps that offer sign-in with Apple, so add a proper re-authentication step before App Store work. |
| 6 | `email` has no UNIQUE index (enforced in code only). | Not changed; a migration on live data was out of scope. |

## Migration impact
Additive only: three new tables (`auth_identities`, `oauth_flows`, `oauth_tickets`) created with `CREATE TABLE IF NOT EXISTS` at startup. No column changes, no data rewrites, no password resets. Existing rows are never read or modified except by normal login.

## Provider sign-in design
Server-side OpenID Connect authorization-code flow with PKCE, `state` and `nonce` stored in the database (single use, 10 min). The id_token signature (provider JWKS), issuer, audience, expiry and nonce are verified. The session token never appears in a URL: the callback redirects to the app with a single-use 5-minute ticket in the URL fragment, which the page swaps for a session via `POST /auth/exchange`.

Account linking: an identity is `(provider, subject)`, never an email. If a provider account's **verified** email matches an existing account, nothing is merged. The page asks for that account's Loominous password (`POST /auth/link`, 5 wrong tries burns the ticket). An unverified provider email that matches an account is refused. A provider-only account created fresh gets a random unusable password.

Everything is off unless the provider's environment variables are set, and `GET /auth/providers` tells the page which buttons to show.
