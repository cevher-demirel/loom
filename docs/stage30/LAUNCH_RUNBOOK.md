# Stage 30 launch runbook (nothing here has been executed)

Order: A backend (Google OFF) -> B frontend -> C private Google test. Each phase starts only after your explicit approval. Stop at the first failed check.
Compatibility during the staged rollout: the new page against the OLD backend hides the Google button (its `/auth/providers` call fails -> buttons stay hidden); the OLD page against the NEW backend works (login/signup/recovery endpoints unchanged; the only new rule is that NEW usernames cannot contain "@"). So A-before-B and B-before-A are both safe, A first is preferred.

## Before Phase A
1. Fresh Turso backup now (the Nov 9 export predates later activity): `turso db export loom` (WSL) or the dashboard; check `PRAGMA integrity_check` = ok and counts; store it inside your encrypted volume. Note Turso's point-in-time restore window as a second safety net (restore creates a NEW database; it never overwrites `loom`).
2. Render dashboard > loom-phas: note the current Live deploy (for rollback); confirm Settings > Build: GitLab loominous, branch `main`; Environment: NO `GOOGLE_*`, `APPLE_*`, `PUBLIC_API_BASE`; leave `FRONTEND_URL`, `TURSO_*` as they are. Do not paste values.
3. GitLab: MR !1 pipeline green (or you accept the local results below).

## Phase A: backend, Google OFF (after your approval to merge)
Merge MR !1 into `main`. Render builds (watch the log for pyjwt/cryptography installing). Then check:
- `curl https://loom-phas.onrender.com/health` -> ok
- `curl https://loom-phas.onrender.com/auth/providers` -> `{"google":false,"apple":false}`
- `curl -i https://loom-phas.onrender.com/auth/google/start` -> 404
- Sign in to the live site with your own account (old page): your dreams are there; create a test dream and delete it, or just open one.
- Counts unchanged: from your own shell with Turso variables, `python scripts\db_counts.py --configured-backend --i-am-the-operator` -> 65 users, 183 dreams (+ anything new since the backup); schema hash differs only by the three new tables.
- Render log: no `schema_warning`, no errors.
Fail -> Render dashboard > Events/Deploys > roll back to the previous deploy. The new tables stay (empty, ignored by old code); nothing needs undoing in the database. Application rollback does NOT reverse database changes, and none is needed here because the migration only adds tables.

## Phase B: frontend (after Phase A passes and you approve)
`python scripts\build_frontend.py` -> `dist\` contains exactly `index.html`, `assets/login/login-desktop.webp`, `assets/login/login-mobile.webp`. Upload that folder to Cloudflare Pages (Direct Upload; note the current deployment first). Check: desktop and phone width sign-in page and artwork; sign in, sign up (use a throwaway), forgot password email, logout; your old dreams open; Google button hidden. Fail -> Cloudflare Pages > Deployments > previous deployment > Rollback/promote.

## Phase C: private Google test (after B is stable)
Google Cloud Console: project, OAuth consent screen in **Testing**, your Google account as the only test user, scope `openid email profile`; Web client; authorised redirect URI exactly `https://loom-phas.onrender.com/auth/google/callback`. You type the client id/secret into Render yourself: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `PUBLIC_API_BASE=https://loom-phas.onrender.com`, `FRONTEND_URL=https://loominous.org`. Redeploy. Then: new Google account; link to an existing account (password required); wrong password refused; second sign-in; logout/login; sign in on iPhone Safari; start account deletion on a Google-only test account and STOP before the final delete button; tell me whether the re-verification step passed or was refused. Disable at any time: remove `GOOGLE_CLIENT_ID` on Render and redeploy.
Public Google needs: the deletion result, a privacy policy and app home page, moving the consent screen to production, and a decision on Render's free-tier sleeping.
