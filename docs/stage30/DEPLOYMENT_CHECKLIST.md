# Stage 30 deployment checklist (nothing below has been done)

Gate legend: [OWNER] you do it / approve it. [CLAUDE] I can do it only after the stated approval.

## 0. Before pushing
- [x] Real-backup copy check PASS (65->65 accounts, 183->183 dreams, repeat-safe, 0 identity conflicts).
- [x] Shared-email / no-email linking reviewed and fixed (EXISTING_DATA_AND_LINKING.md).
- [ ] [OWNER] Approve: push branch `stage-30-release-prep` to GitLab (new branch only; no force; main untouched).

## 1. Merge request (after the push)
- [CLAUDE/OWNER] Open MR `stage-30-release-prep` -> `main` using MERGE_REQUEST.md. Do not merge.
- [ ] CI pipeline `tests-fast` green. `tests-browser` run once manually (fix image tag if it fails to pull).
- [OWNER] Check GitLab CI/CD settings: shared runners enabled; no secret variables needed (tests use placeholders).

## 2. Settings to verify by name only (dashboards; do not paste values)
- Render: repo = GitLab loominous, branch = main, auto-deploy on; start command unchanged; env names present: TURSO_DATABASE_URL, TURSO_AUTH_TOKEN, FRONTEND_URL, PUBLIC_API_BASE (set to https://loom-phas.onrender.com); GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET must be ABSENT for step 3.
- Cloudflare Pages: what project/publish folder serves loominous.org; whether it builds from Git or direct upload.
- Google Cloud: client type Web; redirect URI exactly https://loom-phas.onrender.com/auth/google/callback; publishing status Testing; only your account as test user.

## 3. Release step 1: backend, Google OFF  [OWNER approval to merge + deploy]
1. Fresh Turso backup right before (the Nov 9 one predates later activity).
2. Merge MR. Render deploys. Wait for Live.
3. Verify: site loads; an existing account logs in; /auth/providers shows google false; Render log has no schema_warning; dream/account counts unchanged (scripts/db_counts.py with your own shell, counts only).
Rollback: Render -> previous deploy. New tables are additive and may stay.

## 4. Release step 2: frontend  [OWNER approval]
Build `python scripts\build_frontend.py`, upload dist to Cloudflare Pages. Verify desktop and mobile login/signup/logout, Google button hidden, login artwork loads. Rollback: previous Cloudflare deployment.

## 5. Step 3: Google, owner only  [OWNER approval]
Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET on Render yourself; redeploy. Run the owner test list (LIVE_LAUNCH_PLAN.md section 9) with your test Google account; do not press the final delete button; report whether auth_time was present. Disable: remove GOOGLE_CLIENT_ID.

## 6. Later (separate decisions)
Deletion fallback if auth_time missing; publishing status to In production; privacy policy; Render plan; no-email users adding an email.
