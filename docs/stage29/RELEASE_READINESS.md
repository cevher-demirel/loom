# Release readiness (local implementation complete ≠ production approved)

Status key: **Verified** (shown by a local test, with the mock provider) · **Blocked** · **Not tested** · **Requires owner action**.

## A. Code behaviour
| Item | Status |
|---|---|
| State: random, one-time, 10-min expiry, bound to browser by HttpOnly cookie | Verified (mock) |
| Other browser / missing / modified cookie / unknown, altered, expired state rejected | Verified (unit + real-browser) |
| Replay and concurrent callbacks rejected | Verified |
| PKCE S256 enforced by the mock provider | Verified |
| id_token: bad signature, issuer, audience, expiry, nonce, missing sub rejected | Verified |
| Identity by `sub`; no duplicates; changed email OK | Verified |
| No email-only takeover; link needs password; unverified email refused | Verified |
| Concurrent linking / first sign-in safe | Verified |
| Google-only deletion with fresh re-auth; mismatch, expiry, replay, cancel, other-browser | Verified |
| Password login/signup/reset/deletion regression | Verified |
| No secrets/codes in logs; access log redacted | Verified |
| Google hidden until config valid (https, credentials) | Verified |
| Tests never touch production DB | Verified (isolation test) |
| Real Google behaviour (consent, `prompt=login`, `sub`, errors) | **Not tested** |
| Safari / iOS / Firefox cookie behaviour | **Not tested** (Chromium only) |
| Load, multi-instance behaviour (rate limits are per process) | **Not tested** |

## B. Deployment audit (nothing deployed or changed)
| Question | Finding |
|---|---|
| How does Cloudflare Pages get the frontend? | **Cannot be verified.** The repo has no Cloudflare config (no `wrangler.toml`, no build script). Likely a Git-connected Pages project, which is blocked while the GitHub account is suspended. **Requires owner action:** confirm the project's source and build output directory in the Cloudflare dashboard. |
| Is `assets/login/` published? | The files are tracked and referenced relatively (`assets/login/login-*.webp`), so they publish if Pages serves the repo root. Unverified on the live site. |
| Which backend does the frontend call? | Hardcoded `https://loom-phas.onrender.com` (`API_BASE` in `index.html`). |
| How does Render receive updates? | The repo has no `render.yaml`; `CLAUDE.md` says Render deploys from `main`. Blocked while GitHub is suspended. **Requires owner action.** |
| Secrets | Environment variables on the Render service only; never committed. |
| CORS / cookies with `loominous.org` | API uses bearer tokens with CORS `*`, so no cookie is needed cross-site. The only cookie is the short-lived OAuth binding cookie, set by the backend during a top-level navigation and sent back on Google's top-level redirect (SameSite=Lax). **Not tested** in Safari. |
| Schema migration | Additive only (new columns, new unique index). Before release check production has no duplicate `(user_id, provider)` rows. **Requires owner action** (read-only query by the owner). |
| Render / Turso | Untouched; no plan to remove them. |
| When GitHub returns | Review the Stage 29 patch, run CI, merge via PR, confirm Render redeploys, confirm startup `oauth_config` shows no problems, then run the live checklist below. |

## C. Live Google test checklist (prepared, **not performed**)
Environment: isolated backend + throwaway database, dedicated test Google account listed as a test user, separate Loominous test account, secrets only in the host's env.
- [ ] `oauth_config` startup event clean; Google button appears only then.
- [ ] Success: new Google user is created once; signing in again reuses it.
- [ ] Cancel at Google → friendly message, no session.
- [ ] Existing password account with same email → link screen; wrong password rejected; right password links.
- [ ] Unverified Google email refused (if obtainable).
- [ ] Open the callback URL in a different browser/profile → rejected.
- [ ] Reload/replay the callback URL → rejected.
- [ ] Logout then Google login again; session expiry.
- [ ] Deletion: Google-only user sees **Verify with Google**, Google asks for fresh sign-in, final button deletes; cancel and wrong Google account keep the account.
- [ ] Mobile Chrome and **Safari (iOS and macOS)**, plus private mode: binding cookie survives the round trip.
- [ ] Error paths: revoke app access, invalid redirect URI in console, secret mismatch → generic error, nothing leaked to the page or logs.
- [ ] Logs reviewed: no `code=`, `state=`, tokens or secrets.

## D. Owner actions before any production enablement
1. Confirm Cloudflare Pages and Render deployment sources once GitHub is available.
2. Create the Google project/credentials (guide above); supply secrets directly to Render.
3. Decide the callback host question (Render hostname vs `api.loominous.org`).
4. Run the live checklist; only then consider moving the consent screen out of Testing mode.
