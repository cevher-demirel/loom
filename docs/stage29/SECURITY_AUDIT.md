# Stage 29 — Auth security audit

Scope: `oauth.py`, `main.py`, `database.py`, `index.html`, `tests/`, `docs/stage28`, deployment config in the repo.
Baseline: branch `stage-28-auth-design`, commit `e9a7a27`, 864 passing tests. Nothing was pushed, merged or deployed; no production data was read or changed.

## Lifecycle map (as found)
| Step | Mechanism |
|---|---|
| Register | `POST /signup` → PBKDF2-HMAC-SHA256 (200k) hash, session token issued |
| Login | `POST /login` → token rotated on every login (no fixation) |
| Reset | `POST /forgot-password` → emailed single-use token → `POST /reset-password` |
| Google start/callback | `GET /auth/google/start`, `GET|POST /auth/google/callback` (Stage 28) |
| Link | `POST /auth/link` with the existing account's password |
| Session | one bearer token per user, 30-day expiry, `Authorization` header, stored in `localStorage`; logout deletes it |
| Delete | `DELETE /account` (password) |

## Confirmed vulnerabilities (all fixed locally)
| # | Severity | Finding | Exploit scenario | Fix |
|---|---|---|---|---|
| V1 | **High** | OAuth login CSRF: `state` was server-known but not bound to the browser that started the flow. | Attacker starts a login, stops before the callback, sends the callback URL to a victim. The victim's browser finishes the attacker's login and the victim then records dreams in the attacker's account. | Per-flow HttpOnly binding cookie; only its SHA-256 is stored; callback must present it (constant-time compare). |
| V2 | Medium | Flow row read then deleted (non-atomic): two concurrent callbacks could both succeed. | Replay of an intercepted callback in the same instant as the real one. | `DELETE … RETURNING` consumes the flow atomically; failed attempts also burn it. |
| V3 | Medium | Link/ticket consumption and first-time account creation were check-then-act. | Two simultaneous first sign-ins: `UNIQUE` failure (500) or an orphan user row. | Atomic ticket pop; insert-first with retry; orphan user removed if the identity race is lost; added `UNIQUE(user_id, provider)`. |
| V4 | Medium | `uvicorn.access` logged full URLs, including `?code=` and `state=`. | Anyone with log access sees live authorization codes. | Access-log filter redacts the query of `/auth/` paths. |
| V5 | Medium | No validation of `PUBLIC_API_BASE` / `FRONTEND_URL`; an empty `FRONTEND_URL` redirected to the backend itself; http was accepted. | Misconfiguration silently ships an insecure or broken flow. | `oauth.config_problems()` fails safe: Google stays hidden/404 until https URLs and credentials are valid. Names problems, never values. |
| V6 | Medium | `delete_account` left `auth_identities` rows behind. | Orphan identity → crash or re-login into a deleted account's identity. | Deletion also removes identities, tickets and flows; `find_identity` ignores orphans. |
| V7 | Medium | Google-only users had no way to delete their account (no password). | Data-retention/privacy obligation not met. | Fresh Google re-authentication (see below). |
| V8 | Low | No rate limit on the callback. | Cheap state/code guessing and DB churn. | 60 calls / 15 min / IP on callback; start, exchange, link and reauth limited too. |

## Properties verified (no change needed)
Identity is `(provider, sub)`, never email; no email-only merge; unverified Google email refused; state is 256-bit random; PKCE S256 with a server-side verifier; id_token checked for signature (RS256 via JWKS), `iss`, `aud`, `exp`, `nonce`, `sub`; redirects go only to the configured `FRONTEND_URL` (request redirect parameters ignored); provider errors map to fixed codes; session token rotates per login; API uses bearer tokens, not cookies, so classic CSRF does not apply to state-changing API calls (CORS `*` is therefore acceptable).

## Potential risks / legacy issues (not fixed here; documented)
1. Account enumeration through distinct messages (`email_unverified`, signup 409). Low.
2. Session tokens stored in plaintext in the DB; hashing them would be an additive migration. Medium (DB read access required).
3. One session per account: a new login signs the other device out. Product decision.
4. PBKDF2 at 200k iterations is below current OWASP guidance for SHA-256 (600k). Raising it needs rehash-on-login.
5. Rate limits are in-memory per process: reset on restart, not shared across instances.
6. Tokens in `localStorage` are readable by any XSS. The page has no known injection, but this is the standing trade-off of bearer storage.
7. RFC 9207 `iss` response parameter is not checked (Google does not send it; the id_token `iss` is verified).
8. The one-time login ticket in the redirect fragment is not cookie-bound. A cross-origin page cannot attach the SameSite cookie, and the ticket is single-use, 5 minutes and fragment-only (never sent to servers or logged).
9. Sign-in with Apple remains dormant and hidden.

## Remaining risk after this stage
Everything above is verified against a **mock** Google. Real-Google behaviour (consent screen, `prompt=login` handling, mobile Safari cookie behaviour, domain verification) is untested.
