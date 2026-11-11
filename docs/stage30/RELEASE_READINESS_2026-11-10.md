# Stage 30 release readiness (2026-11-10)

Verdict: **READY for a controlled backend deployment with Google OFF**, after the owner conditions below. **NOT READY** for Google for anyone but the owner, and not for public Google sign-in.

## Tests (all run on the final code)
| Run | Result |
|---|---|
| Full suite incl. browser (Chromium), SQLite | **972 passed, 0 failed** (26.5 min) |
| Turso-client path (libsql_client) vs local libSQL server, 12 files | **433 passed, 1 skipped on purpose** (second run). The first run had 1 failure (`test_client_disconnect_mid_stream_releases_claim`) while the full suite was using the CPU; it passed in 5 later runs (alone x3, in sequence x1, whole-file). Stage 21 code, not Stage 30; treated as a timing flake, not proven cause. |
| Real-data copy migration check (owner ran) | PASS: 65->65 accounts, 183->183 dreams, existing tables unchanged, repeat-safe, 0 identity conflicts |
| Synthetic migration rehearsal | PASS |
Not testable here: real Google, real Turso service, Safari/iPhone, the GitLab pipeline itself.

## Changes since MR !1 was opened
1. `.gitlab-ci.yml`: pipelines now start on every branch push (before: only for merge-request events or main).
2. `index.html`: a malformed `%` escape in the address fragment can no longer stop the page script (new browser test; fails without the fix).

## Why MR !1 shows no pipelines (cannot confirm from here; most likely first)
1. The old rules created pipelines only for merge-request events or `main`. The branch was pushed before the MR existed, so the push created none, and an MR does not always create one when it is opened.
2. gitlab.com can refuse to create/run pipelines on a new account until identity verification (credit card, no charge) is done, or when shared runners are off or minutes exhausted. A pipeline page or "Run pipeline" button shows the exact reason.
3. CI/CD disabled for the project (Settings > General > Visibility > CI/CD).
After the new commit is pushed, a pipeline should start by itself. If not, MR page > Pipelines > Run pipeline shows the reason.
Image `mcr.microsoft.com/playwright/python:v1.56.0-noble`: tag format matches Playwright docs; not pulled. Requirements resolve under Python 3.12 (image's Python), checked with a dry-run.

## Independent safety review of the 18 commits / 61 files
No critical or high findings; no secrets or real emails. Migration additive only (3 new tables, never touches users/dreams/profile); safe with 45 empty-email accounts and the shared email; rollback harmless. With no GOOGLE_*/PUBLIC_API_BASE set, Google endpoints return 404, button hidden, nothing logged. CI has no deploy job and no secrets.
Open low items (not changed): `/auth/exchange` and `/auth/link` stay live but inert with Google off; username-existence timing on login (pre-existing); in-memory rate limits; migration race if old and new Render instances overlap (self-heals on restart); `migration_rehearsal.py` would pass a production Turso token from the shell to a `loom-rehearsal*` host (run it with a clean environment); `cryptography` unpinned (watch the first Render build log).

## Conditions before the backend deploy (owner)
1. Fresh Turso backup or restore point immediately before (the Nov 9 export predates later activity).
2. On Render set NO `GOOGLE_*`, `APPLE_*` or `PUBLIC_API_BASE`; leave `FRONTEND_URL` as is.
3. Pipeline green (or explicit acceptance of local results) and explicit approval to merge.
After deploy: `/auth/providers` all false, `/auth/google/start` 404, a legacy account logs in, counts unchanged (`scripts/db_counts.py`), Render build log shows pyjwt/cryptography installed.
Rollback: redeploy the previous Render deploy (new tables are ignored by old code). Cloudflare: Direct Upload only, so frontend rollback = re-upload previous build or promote previous deployment.

## Still unknown / owner decisions
Real Google behaviour (`auth_time`, cancel/replay/wrong account, Safari/iPhone); deletion fallback if `auth_time` is absent; privacy policy; Render free-tier cold starts; no-email users getting a second account if they use Google.

## Addendum (2026-11-10, after pipeline #3050872571)
- That pipeline showed "yaml invalid", 0 jobs and "Verify your identity to run this pipeline". A pipeline refused for an unverified account has no jobs and can carry a generic error badge, so this is most likely the identity requirement (now done by the owner), not a syntax error.
- Checked: both the pushed `.gitlab-ci.yml` (f264f20) and the current file pass GitLab's own CI JSON schema (`check-jsonschema --builtin-schema vendor.gitlab-ci`). NOT verifiable here: GitLab's server-side CI Lint (needs authenticated access); one click covers it: GitLab > Build > Pipeline editor > Validate.
- CI image/Playwright now pinned to 1.63.0 (the version the browser suite was run with locally); `PIP_BREAK_SYSTEM_PACKAGES` kept (harmless). The image tag is still not pulled/verified from here.
- Final tests on this tree: full suite 972 passed; Turso-client path 433 passed, 1 skipped on purpose; clean Python 3.12 checkout non-browser job reproduction 537 passed (42 browser-style tests skipped there because that venv had no Chromium). Frontend build contains index.html plus the two login images and nothing else is referenced locally.
- Step-by-step launch and rollback: `LAUNCH_RUNBOOK.md`.
