# Stage 30 production-readiness review (read-only)

Date 2026-11-09. Nothing was merged, pushed, deployed or changed; no production data, Render, Cloudflare, Google or Turso access. Facts marked **UNVERIFIED** need the owner to check a dashboard.

## 1. GitLab state and what a release changes
**Migration result (from `migration-result.txt` on your PC, produced by the script's own fresh-clone check; I cannot reach GitLab myself):** `main` fast-forwarded from the initial commit `56e9750` to `cd29991`; 6 stage branches created; all 8 tree checks PASS (main == production `166ac63` file tree; stage-30-phase-b-prep tree == local `e8b504c`); GitLab's initial commit kept; clone not shallow; fsck clean. Note: the file tree on GitLab `main` equals production code, but its *commit hashes* differ from the old GitHub ones.
**What releasing Stage 30 means:** merge request `stage-30-phase-b-prep` -> `main` (14 commits, 48 files). Production-affecting files only:
| File | Change |
|---|---|
| `oauth.py` | new (395 lines): Google sign-in, token checks, reauth freshness |
| `main.py` | +224: routes `/auth/providers`, `/auth/{provider}/start|callback`, `/auth/exchange`, `/auth/link`, `/account/reauth/{provider}`; `DELETE /account` accepts a Google reauth ticket |
| `database.py` | +379: new tables `auth_identities`, `oauth_flows`, `oauth_tickets` (+3 columns on `oauth_flows`), unique index, identity functions, deletion cleanup |
| `index.html` | +687: new login design, Continue with Google, linking and deletion UI, interaction fix |
| `assets/login/*.webp` | new, 338 KB (must be deployed with the page) |
| `requirements.txt` | adds `pyjwt[crypto]==2.15.0` (Render installs it on build) |
| `.gitignore`, `pytest.ini`, docs, tests, scripts | no runtime effect |
Existing tables (`users`, `dreams`, ...) are not altered. The MR is the "exact change"; no other code is required. After merge, Render redeploys the backend; the frontend needs a separate Cloudflare upload.

## 2. Google configuration (loominous.org / loom-phas.onrender.com)
| Item | Value |
|---|---|
| Redirect URI (the only one needed) | `https://loom-phas.onrender.com/auth/google/callback` |
| `loominous.org` | **Not a redirect URI.** It is the frontend; the browser returns there from the backend, not from Google. Use as home page / authorized domain only |
| Authorized JavaScript origins | none |
| Scopes | `openid email profile` |
| Publishing status | **Testing**, only your account as test user (Google then blocks everyone else). Expect Google's "app not verified" warning screen for you; continue via Advanced |
| Render env (names) | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `PUBLIC_API_BASE=https://loom-phas.onrender.com`, `FRONTEND_URL=https://loominous.org` (no trailing slash/path) |
| Client | Recommend a **separate live client** (e.g. `loominous-live`) with only the Render redirect URI, not the `loominous-local-test` client that also lists localhost addresses. Owner decision; either works technically |
Backend logs `oauth_config` at start: it lists problem *names* only. `/auth/providers` returns `{"google": true}` only when all four are valid, and the page hides the button otherwise (also when the backend is older than the page).

## 3. Google-only deletion and re-authentication
Rules in code (`DELETE /account`): a Google-only account (no usable password) can be deleted **only** with a one-time `reauth_ticket`; password accounts use their password; tickets are single-use, expire in 5 minutes, bound to the account's own linked Google identity, rate limit 5 per 15 min. The ticket is issued only if Google's ID token passes signature/issuer/audience/expiry/nonce checks **and** `auth_time` is present, <=5 min old, not before the flow began, not in the future. A missing `auth_time` is refused (fail closed).
**Covered by mock tests (968 passing):** every rule above, replay, wrong account, other browser, cancel, stale/missing/future `auth_time`.
**Real-provider gaps (cannot be closed without real Google):**
1. Does Google return `auth_time` when asked via `claims` (documented as the way)? If not, Google-only users cannot delete until the email-confirmation fallback exists.
2. Does Google ignore `prompt=login`/`max_age` (not documented)? If so, a silent session reuse gives an old `auth_time` -> refused (safe but blocks deletion).
3. Cancel at Google, other-browser rejection, callback replay, link-with-password, wrong Google account: only proven with the mock.
4. Safari/iPhone/Firefox; the Render cold-start during sign-in.
5. **Turso behaviour (new finding):** all tests run on SQLite. The Turso path (`libsql-client` 0.3.1) is not exercised, including the atomic one-time claims `DELETE ... RETURNING` that replay protection relies on (SQLite and libSQL both support RETURNING, but this exact client path is untested). Rehearse on a Turso *copy* before production (section 5).
Non-destructive owner test: start Delete account -> Verify with Google -> **stop before the final button**; the log line `oauth_reauth_check auth_time_present` is the answer.

## 4. Turso backup (do before anything touches production) - owner runs; I never see data
The backup contains everything (dreams, emails, password hashes, session tokens): keep it **only on your encrypted PC/drive, never in the repository, GitLab, chat or this workspace.**
Documented methods (Turso docs): (a) SQL dump `turso db shell <db> .dump > loominous-YYYYMMDD.sql`; (b) a copy database `turso db create loominous-backup-YYYYMMDD --from-db <db>` (new name only, counts toward the plan's database quota; the original is not changed); (c) point-in-time restore `... --from-db <db> --timestamp <RFC3339>`, retention Free 24 h / Developer 10 d / Scaler 30 d / Pro 90 d (create-new only; needs a new token). Read-only nature of `.dump` is not stated by the docs; it is a read in practice, which is why the copy in (b) plus counts is the cross-check.
Procedure: 
1. Pick a quiet moment; note the time (UTC).
2. Take **both** (a) and (b).
3. Verify with counts (no content): `python scripts/db_counts.py --configured-backend --i-am-the-operator > counts-prod.txt` (production credentials only in your own shell) and the same against the copy (set `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN` to the copy's) `> counts-copy.txt`; then `python scripts/db_counts.py --compare counts-prod.txt counts-copy.txt` must say `identical` (it compares table row counts and the schema hash; run it while nobody is using the site, or expect small differences from live activity).
4. Prove the dump restores: `turso db create loominous-restore-test --from-dump loominous-YYYYMMDD.sql`, run the counts script against it, compare again, then delete the test database yourself.
5. Record file size and SHA-256 of the `.dump` (`Get-FileHash`), store a second copy elsewhere.
The counts script was tested on synthetic data: no user text in output, SELECT-only (it refuses anything else), exit codes 0/1/2.

## 5. Migration risks, existing accounts, rollback
| Risk | Assessment | Mitigation |
|---|---|---|
| Existing accounts/dreams altered | No: additive `CREATE TABLE IF NOT EXISTS`, `ALTER` only on the new `oauth_flows`; nothing rewrites `users`/`dreams` (9 synthetic migration tests, crash injected at every statement) | Backup + counts before and after |
| Unique-index creation fails on odd data | Cannot stop the server (logs `schema_warning`, skips); duplicates impossible while the old UNIQUE exists | Read-only preflight `scripts/preflight_auth_identities.py --configured-backend --i-am-the-operator` expecting "no auth_identities table yet" |
| Turso-specific behaviour untested | Real, unverified (section 3.5) | **Rehearse on a Turso copy:** create `loominous-restore-test` from the dump, point a *local* backend at it (`TURSO_DATABASE_URL` for the copy only), start it, and exercise sign-in with the mock-free flow only after Google is configured; at minimum start the backend and confirm no `schema_warning`, `/auth/providers`, ordinary login, then compare counts |
| Old and new instances overlapping during Render deploy | Safe: additive schema; old code ignores new tables | none |
| Rollback of code | Safe for data: old code ignores the new tables. **Nuance:** anyone who *signed up with Google* has a random unknown password, so after a code rollback they cannot sign in until the new code returns (their data stays). Accounts that only linked Google keep password login | Keep rollback for the pre-public stage; do not publish Google before the system is stable |
| Rollback of data | Restore only from the Turso backup into a **new** database and switch the connection string (restore is create-new only); this discards later activity, so it is a last resort needing a decision | Take the backup immediately before the release |
| Rollback of Google only | Remove `GOOGLE_CLIENT_ID` (or the secret) on Render: button disappears, routes refuse. No data change | |

## 6. CI now that GitHub Actions do not run
Nothing runs automatically today: the tests workflow, and the four manual Claude/preview workflows, are GitHub-only. The Claude-pilot and visual-preview workflows are manual and need GitHub secrets; do not port them. Needed: the test workflow only. Draft in `docs/stage30/gitlab-ci.draft.yml` (YAML parses; not run on GitLab; the Playwright image tag is UNVERIFIED with a documented fallback). Budget: GitLab Free gives 400 compute minutes/month (private projects, cost factor 1). Measured locally: 576 non-browser tests 4 min, 392 browser tests ~22 min, whole suite 26 min. Plan: fast job on every MR and on `main`; browser job on `main` and manual on MRs (about 15 browser runs a month). In GitLab settings: keep `main` protected, require merge requests, enable "pipelines must succeed", and **do not add production secrets as CI/CD variables.** Until the pipeline exists, run `python -m pytest -q` locally before each merge (full suite last run: 968 passed).

## 7. Recommended order (each step separately approved; none done)
0. **Prepare (no production change):** Turso backup + verification (section 4); preflight; Turso-copy rehearsal; install the CI file via an MR; confirm Cloudflare Pages settings (source, build, output) and Render settings (branch `main`, start command, instance type); decide the Google client; create the Google client/test user (Google console change, approval needed).
1. **Backend first, Google OFF:** merge the MR (owner approval), let Render deploy the new code **without** any `GOOGLE_*` variables. Verify: site loads, existing login works, dream counts equal the pre-release counts (`db_counts`), logs show no `schema_warning`, `/auth/providers` -> google false. Roll back by redeploying the previous Render deploy if anything is off.
2. **Frontend:** upload the new page to Cloudflare Pages (preferably only `dist/` from `scripts/build_frontend.py`: `index.html` + 2 images; check `https://loominous.org/assets/login/login-desktop.webp` loads). The Google button stays hidden. Verify design, login, signup, logout, mobile widths. Roll back to the previous Cloudflare deployment.
3. **Google ON, owner only:** you enter `GOOGLE_CLIENT_ID`/`SECRET` and the two URL variables on Render; wake the service first (cold start ~1 min, UNVERIFIED); check the `oauth_config` log; Testing mode keeps everyone else out. Owner test: sign-in, correct account, logout, repeat sign-in same account and dreams, cancel at Google, private-window rejection, Back button, **non-destructive deletion check (stop before the final button; record `auth_time_present`)**.
4. **Decide:** if `auth_time` is present and fresh -> deletion is proven; otherwise build the email-confirmation fallback (approval) before any public availability.
5. **Public availability** is a separate, later decision (Google publishing needs a privacy policy and home page; Render free tier is "not meant for production").

## 8. Blockers
| Blocker | Applies to |
|---|---|
| No verified Turso backup yet | any production change |
| Turso code path untested (RETURNING etc.) | production deploy with Google on |
| Cloudflare and Render settings unverified (Cloudflare may publish the whole repo incl. docs/source) | frontend deploy |
| `auth_time` unproven with real Google | public availability, not the owner-only test |
| No CI yet; GitLab minutes are limited | merges (mitigated by local full-suite run) |
| Safari/iPhone untested; privacy policy missing; Render free tier | public availability |

## 9. Release checklist for approval
- [ ] A. Turso dump + copy taken, counts identical, dump restore-tested (owner)
- [ ] B. Preflight run read-only against production, expects no conflicts (owner or approved operator)
- [ ] C. Rehearsal against a Turso copy passes (owner/approved)
- [ ] D. Cloudflare Pages and Render settings confirmed (names only, no secrets)
- [ ] E. CI file merged via MR; local `python -m pytest -q` green on the MR commit
- [ ] F. **Approval to merge `stage-30-phase-b-prep` into `main`** (Render deploys, Google OFF)
- [ ] G. Backend smoke test and counts equal; sign-off
- [ ] H. **Approval to upload the frontend to Cloudflare**; smoke test; sign-off
- [ ] I. **Approval for Google Cloud client/test-user changes**; owner enters the four Render variables
- [ ] J. Owner-only Google test incl. non-destructive deletion check; report `auth_time_present`
- [ ] K. Decision on deletion fallback (if needed) and on public availability
