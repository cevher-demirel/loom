# Stage 30 release report (2026-11-09/10)

Branch `stage-30-release-prep` (from `stage-30-phase-b-prep`), local commits only. Nothing pushed, merged, or deployed. Production Turso, Render, Cloudflare, Google, and the encrypted backup were not accessed. No real user data was used or seen. Everything below was actually run unless marked NOT TESTED.

## Verdict
* **READY for Step 1 of the staged release** (merge to `main` with Google sign-in OFF, backend first), **after** the owner steps in section 5 (copy-check on the backup, Render/Cloudflare settings check, CI/merge approval).
* **NOT READY for Google sign-in to be switched on for anyone but the owner, and NOT READY for public availability.** Reasons: real-Google behaviour is still unproven (deletion `auth_time`, cancel, replay, linking, wrong account, Safari/iPhone), the real Turso service itself is untested (the Turso client path was proven against a local libSQL server only), and the Render free tier / privacy policy items remain.

## Tests (actual results)
| Run | Result |
|---|---|
| Full default suite `python -m pytest -q` (SQLite, mocks) | **969 passed, 0 failed, 0 skipped** (26 min) |
| Same code paths through the **Turso client** (`libsql_client`) against a local libSQL server: database, OAuth, API, stage and legacy-data tests (11 files) | **423 passed, 1 skipped** (the skip asserts "no Turso", intentionally) |
| Migration rehearsal (old production code `166ac63` -> new code), 65 synthetic accounts / 183 dreams / 40 profiles | **PASS** (below) |
| Synthetic WAL-mode backup through `migrate_copy_check.py` | **PASS**, original untouched, temp copy removed |
| Real Google, real Turso service, Safari/iPhone, Render, Cloudflare | **NOT TESTED** (not reachable from here / needs owner) |

Coverage of the areas you listed (all with mock providers, real browser where noted): email/password login, registration, recovery, logout, session expiry (`test_main`, `test_database`, `test_oauth`); Google sign-in and sign-up, linking to an existing account (never merged), duplicate prevention, replay, wrong browser, cancel, concurrent attempts (`test_oauth`, Chromium `test_stage29_google_e2e`, `test_stage30_https_env` over HTTPS cross-site); account deletion incl. Google-only reauthentication, stale/missing/future `auth_time`, wrong identity, expired verification (`test_oauth`, Chromium `test_stage30_interaction`); mobile/desktop auth screens and login artwork (`test_stage28_login`, `test_stage30_assets`); existing journal, dream detail, Loom Map and Insights suites (stage 19–27 browser tests and `test_main`) all still pass.

## Database rehearsal (separate server, synthetic data only)
Old code built the old schema and 65 accounts / 183 dreams / 40 profiles. New `init_db()` ran three times (three restarts). Existing tables: **identical** (row counts, SHA-256 of every row, columns). New: `auth_identities`, `oauth_flows`, `oauth_tickets`, empty. Repeats change nothing. All 65 accounts still sign in; `/login` + `/dreams` counts match; identity rules hold; one new Google account -> 66 users, 183 dreams. Confirmed: **Stage 30 does not remove or overwrite existing account or dream data**; the only DELETEs added operate on the new tables or inside `delete_account` for the deleting user.
Execution is controlled: the migration is idempotent (`IF NOT EXISTS`, column checks), runs at every start, and cannot stop the server on a bad unique index (logs `schema_warning`).

## Bugs fixed on this branch
1. **Legacy mixed-case email**: Google sign-in would create a second account instead of offering to link, if an old row's stored email had capitals (`find_user_by_email` now case-insensitive; regression test fails without the fix). Production emails are probably all lowercase (signup lowercases), but old rows are unverified; the copy-check reports the count.
2. Test-suite only: backend-neutral row handling; opt-in Turso-path mode.

## Changes on the branch (vs `stage-30-phase-b-prep`)
`database.py` (1 query), `tests/` (new regression test; opt-in libSQL mode; backend-neutral row handling), `scripts/migration_rehearsal.py`, `scripts/migrate_copy_check.py`, `.gitlab-ci.yml` (image tag UNVERIFIED until the first pipeline runs), docs.

## Remaining risks
1. Real Google: `auth_time` with `claims` (documented but unseen), `prompt=login`/`max_age` possibly ignored, cancel/replay/linking/wrong-account live, Safari/iPhone, cold-start timing. Safe failure mode: deletion is refused (fail closed). Fallback (email confirmation link) not built; needs your approval.
2. Real Turso service behaviour (latency, plan limits) untested; mitigated by the libSQL-server proof and an optional `loom-rehearsal-…` scratch database run.
3. Render and Cloudflare settings unverified by me (names only to check: Render branch `main` on GitLab, start command, env var names `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `PUBLIC_API_BASE`, `FRONTEND_URL`, `TURSO_*`; Cloudflare source/build/output dir, that `assets/login/*.webp` is served).
4. Backend rollback after Google sign-ups leaves those users unable to sign in until the code returns (data intact).
5. GitLab CI untested on GitLab; free tier 400 minutes/month.
6. The production backup exists and is verified by you, but I did not touch it.

## Exact deployment steps (each needs your approval; nothing done)
**A. Owner prerequisites (no production change)**
1. Mount the encrypted backup; from a checkout of `stage-30-release-prep` run `python scripts\migrate_copy_check.py --db "<exported .db>"`; expect `RESULT: PASS`, accounts 65->65, dreams 183->183; send me only the printed lines.
2. Optional: scratch Turso DB `loom-rehearsal-…`; `python scripts\migration_rehearsal.py --url <libsql url> --allow-remote-scratch` with that DB's token in your own shell.
3. Confirm the Render and Cloudflare settings listed above (names only).
4. Push `stage-30-release-prep` to GitLab (you or approve me), open the merge request, let the pipeline run once (fix the image tag if needed).
**B. Release Step 1 - backend, Google OFF**: approve the merge into `main`; Render deploys; do NOT set `GOOGLE_*` yet. Check: site loads, a known account logs in, dream count equals before (use `scripts/db_counts.py` before/after), `/auth/providers` shows google false, no `schema_warning` in logs. Rollback: redeploy the previous Render deploy.
**C. Step 2 - frontend**: upload `dist/` (`python scripts\build_frontend.py`) to Cloudflare Pages; check design, login/signup/logout, mobile width, `https://loominous.org/assets/login/login-desktop.webp`. Rollback: previous Cloudflare deployment.
**D. Step 3 - Google, owner only** (Testing mode, only your account as test user): you set the four variables on Render; owner test list in `LIVE_LAUNCH_PLAN.md` section 9; stop before the final delete button; record `auth_time_present`.
**E. Step 4** decide deletion fallback; **Step 5** public availability is a separate later decision.

## Merge request text (for GitLab)
Title: *Stage 30: Google sign-in, new login design, additive auth tables*
Body: Adds Continue with Google (server-side code flow, PKCE, state/cookie binding, nonce), account linking by password (never auto-merged), fail-closed Google re-authentication for account deletion, new login screen, and three new tables (additive, idempotent). No change to existing tables. Google is hidden unless `GOOGLE_*`, `PUBLIC_API_BASE`, `FRONTEND_URL` are set on the backend. Tests: 969 passed (full), 423 passed through the Turso client path against a local libSQL server, migration rehearsal on 65 synthetic accounts / 183 dreams passed. Not tested: real Google/Turso/Safari. Deploy order: backend (Google off) -> frontend -> Google for owner only. Rollback: redeploy previous Render/Cloudflare deploy; remove `GOOGLE_CLIENT_ID` to disable Google.
