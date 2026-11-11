# Live Google sign-in on loominous.org: readiness, launch plan, approvals

Prepared locally from the repository and public documentation. **No live service, dashboard, database or Google setting was contacted or changed** (project rule: no live requests). Anything marked UNVERIFIED must be checked by the owner in the dashboards.

## 1. Verdict
**Not ready to enable for the public. Ready for a controlled owner-only test once the approvals in section 8 are given.** Two things block going live: (a) the Stage 28-30 code exists only in this local repository (GitHub suspended, so Render cannot receive it) and (b) account deletion for Google-only accounts cannot yet be proven fresh with real Google (section 5).

## 2. What already works (local, mock Google, one real-Google local run)
Continue with Google button (hidden until the server is configured), start/callback routes, PKCE S256, per-flow state + browser-bound cookie, nonce, RS256 signature/issuer/audience/expiry checks, single-use flows and tickets (replay), `(provider, sub)` identity, link to an existing email account only after that account's password, duplicate-account prevention, fragment-only return to the frontend, logout, repeat sign-in, additive and idempotent migration, 967+ automated tests green. Owner-run real-Google test on a local isolated stack: sign-in, redirect, Home, logout, repeat sign-in worked.

## 3. Addresses (exact values from the code and your messages)
| What | Value | Status |
|---|---|---|
| Production frontend | `https://loominous.org/` | Given by owner. Cloudflare Pages project, source and settings UNVERIFIED |
| Backend | `https://loom-phas.onrender.com` (hardcoded `API_BASE` in `index.html`) | In code; live service settings UNVERIFIED |
| Start route (not registered with Google) | `https://loom-phas.onrender.com/auth/google/start` | Code |
| **Callback route / redirect URI to register** | **`https://loom-phas.onrender.com/auth/google/callback`** | Code (`oauth.redirect_uri`). You said this exact URI is already registered in your Google client |
| Backend env | `PUBLIC_API_BASE=https://loom-phas.onrender.com`, `FRONTEND_URL=https://loominous.org` | Must be set on Render (names only; values are not secrets) |
| Where the browser lands after Google | `https://loominous.org/#oauth_ticket=...` (fragment, cleared by the page) | Code |

## 4. Cross-site behaviour (CORS, cookies, HTTPS, sessions)
API uses `Authorization: Bearer` with CORS `*`, no cross-site cookies. The only cookie is the per-flow OAuth binding cookie: host-only on the Render host, HttpOnly, Secure, SameSite=Lax, Path=/auth, 10 minutes, set and read only by top-level navigations. This pattern is verified in Chromium against a cross-site local topology (127.0.0.1 vs localhost) with real Google. **Not verified:** Safari/iOS (ITP), Firefox. The session is a bearer token kept by the page; persistence after reload/close was covered by tests, live behaviour UNVERIFIED. Render free tier sleeps after 15 minutes; the first Google sign-in after idle takes about a minute (UNVERIFIED live); wake the service (open the site) before the test.
An own-domain callback (`api.loominous.org`) is optional and not needed for the test (see `DEPLOYMENT_AUDIT.md`).

## 5. Account-deletion re-authentication and `auth_time` (research result)
Google's OpenID Connect reference documents: authorization `prompt` values `none`, `consent`, `select_account` only; **no `max_age` and no `prompt=login`**; and `auth_time` is returned **only if requested through the `claims` request parameter**. The previous code sent `prompt=login&max_age=0` and no `claims`, so real Google would very probably omit `auth_time`, and the fail-closed check would **always refuse** deletion for Google-only accounts (safe, but it would block deletion).
**Change made (local, tested):** the Google deletion request now also sends `claims={"id_token":{"auth_time":{"essential":true}}}`. Checks are unchanged and fail closed (present, <=5 min, not before the flow began, not in the future).
**Still unknown until the live test:** (i) whether Google then returns `auth_time`; (ii) whether, with `prompt=login`/`max_age` possibly ignored, Google silently reuses an existing session, in which case `auth_time` would be old and deletion is refused. Both outcomes are safe; neither can be solved without trying real Google.
**If either fails (expected fallback, needs your approval before I build it):** a single-use confirmation link emailed to the account's verified address, valid 10 minutes, bound to the deletion flow, required in addition to the Google identity check. The email sender already exists in the code. Until then the safe interim is to keep Google-only deletion refusing, or to route those requests through the owner. Do not weaken the check.
Owner test (non-destructive, section 9 step 9): start "Delete account", complete "Verify with Google", and **stop before the final Permanently delete button.** The server log line `oauth_reauth_check auth_time_present` (true/false, no values) tells us the answer.

## 6. Data preservation
Migration is additive and idempotent (`MIGRATION_SAFETY.md`); `users` and `dreams` rows are never rewritten; a failing unique index cannot stop the server; a crash injected at every migration statement left data intact. Rolling back code is data-safe: old code ignores the new tables. Not done (needs approval): the read-only production preflight; **take a Turso backup/export or branch first** (owner action in the Turso dashboard). I have not read production data. No existing production account would be modified by the deployment; a Google user whose verified email matches an existing account is asked for that account's password before linking, never auto-merged.

## 7. Blockers and risks
| # | Item | Severity |
|---|---|---|
| 1 | Code not deployable: GitHub suspended; production `main` lacks Stages 27d-30. Deploying brings **all** unreleased stages (UI polish, login redesign, auth) live at once | Blocker |
| 2 | Deletion freshness for Google-only accounts unproven (section 5) | Blocker for *public* launch; not for the owner-only test |
| 3 | Production settings UNVERIFIED: Cloudflare source/build/output (may publish repo root incl. source and docs), Render start command, env vars, instance type | Blocker until checked |
| 4 | Preflight not run; no verified production backup | Blocker for deploy |
| 5 | Google app must stay in **Testing** (only listed test users can sign in). Publishing to production needs privacy policy/home page and possibly verification | Gate for public launch |
| 6 | Render free instance sleeps; "not meant for production use" | Risk |
| 7 | Safari/iOS/Firefox untested; app-store readiness not assessed | Risk |
| 8 | Public email+password registration already exists independently of Google | Note |
Privacy: no secrets in the repository (scanned); logs record only names/booleans/status codes; Google gives us email, name and a stable id (`sub`); a privacy policy link will be required to leave Testing mode.

## 8. Approvals required (each separately)
1. **Deploy path** (pick one): (a) restore GitHub, merge the stage branch to `main` yourself or approve me to; (b) host the repo on GitLab/Bitbucket and reconnect Render (Render lists these providers; the deploy page I could read did not confirm details: UNVERIFIED); (c) Render manual deploy from a Docker image or public Git URL (Render says these "must be deployed manually"). Frontend: Cloudflare Pages Direct Upload via Wrangler or drag-and-drop (limits 20,000 files / 1,000 files, 25 MiB each); drag-and-drop is not available if the project is Git-connected and a Direct Upload project cannot later switch to Git; I could not confirm whether an existing Git-connected project can use Wrangler (UNVERIFIED), so check in the dashboard.
2. Owner takes a Turso backup, then approves a **read-only preflight** against production (or approves me to read counts only).
3. Approval to set Render env vars (you enter secrets yourself): `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `PUBLIC_API_BASE`, `FRONTEND_URL`. **Missing today (names only):** all four unless already set; existing production secrets (Turso, Anthropic, Voyage, Pinecone, Resend) are not changed.
4. Approval for any Google Cloud change. Required values: project in **Testing**, your account listed as test user, scopes `openid email profile` only, client type Web application, **Authorized JavaScript origins: none**, **Authorized redirect URI: `https://loom-phas.onrender.com/auth/google/callback`** (exact; already registered per your message; allow up to a few hours for changes). Optional: authorized domain `loominous.org`, home page `https://loominous.org`.
5. Approval to build the email-confirmation fallback if section 5 fails.
6. Approval to publish the Google app to production only after blockers 2, 5 and privacy-policy are done. **Not requested now.**

## 9. Exact launch steps (after approvals; owner performs dashboard steps)
1. Back up: Windows backup `2026-11-08-5803a1c` (done); export/backup Turso; note current Render deploy ID and Cloudflare deployment ID (for rollback).
2. Run the preflight (read-only) with the operator's own credentials; expect exit 0.
3. Render: set the four env vars (secret typed only into Render's field). Deploy the approved commit. Watch the log: `oauth_config` shows no problems, no `schema_warning`; `/auth/providers` (public GET) lists google.
4. Cloudflare Pages: deploy the frontend for the same commit (preferably only `dist/` from `python scripts/build_frontend.py`).
5. Smoke test, signed out: `https://loominous.org/` loads, login art loads, email login works for an existing account (owner), nothing else changed.
6. Controlled Google test (owner only; Testing mode blocks everyone not listed): Continue with Google -> Google chooser -> back to `https://loominous.org/` signed in as the right account; address bar clean.
7. Logout; sign in with Google again; same account, same dreams (spot check count and one title).
8. Failure checks: cancel at Google (returns to sign-in with a message, no account); open the Google URL in a private window (rejected); press Back after success (no re-login loop, no error loop).
9. Deletion check, **non-destructive**: Settings -> Delete account -> Verify with Google; confirm the log shows `oauth_reauth_check`; **do not press the final delete button.** Report `auth_time_present`.
10. Ask a second test user (added in Google as test user) only if you want to test first-time registration; use a throwaway Google account and delete it afterwards only via a method approved by you.
## 10. Rollback
- Backend: Render dashboard -> select the previous successful deploy and redeploy it (Render rollback docs UNVERIFIED here; the deploy hook with a commit SHA is a documented alternative). Data stays valid because the migration is additive.
- Frontend: redeploy the previous Cloudflare deployment (record its ID first).
- Disable Google sign-in instantly without redeploying: delete `GOOGLE_CLIENT_ID` or `GOOGLE_CLIENT_SECRET` from Render env (button disappears, routes refuse). Or set the Google app's test-user list empty.
- Data: restore from the Turso backup only if data was damaged (not expected). Do not restore over later user activity without a decision.
