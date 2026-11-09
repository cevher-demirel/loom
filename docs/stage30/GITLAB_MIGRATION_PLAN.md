# GitLab migration: readiness and exact steps (NOTHING has been pushed or changed)

Target: `https://gitlab.com/loominous-group/loominous` (private; contains one initial README commit on `main`, not inspected: it needs your login).

## 1. Readiness findings (local audit)
| Check | Result |
|---|---|
| Remotes | Only `origin` = `https://github.com/cevher-demirel/loom` (suspended). No GitLab remote yet. |
| Local branches | main `4e682a7` (**stale**, 2 commits behind `origin/main`), stage-27c, 27d, 28, 29, stage-30-integration-prep, **stage-30-phase-b-prep** (latest Stage 30 incl. Google auth, fail-closed deletion check, launch plan). 77 remote-tracking refs (GitHub branches, mostly `automation/*`): not migrated. |
| Stage 30 preserved | Yes. `origin/main` (`166ac63`) is an ancestor of the Stage 30 branch; all 103 commits reachable. Nothing is uncommitted. No stash, no tags. |
| Tracked/untracked files | No `.env`, `.db`, key, certificate, export or log tracked or ever committed (full history, names). Ignored and never uploaded: `loom.db`, `__pycache__`, `.pytest_cache`. `.env.test.example` holds only blank values. SQL fixtures are schema-only (no INSERT). |
| Content scan of all history | No Anthropic/AWS/GitHub/GitLab/Resend/Pinecone/Voyage/Turso token, JWT or private key. Hits are placeholders: one `sk-ant-` line in an old README commit (24 characters; real keys are ~100) and fake `GOCSPX-`/`libsql://example.invalid` values in tests. **Please glance at `README.md` line 61 in commit `3cfe74b` to be certain.** |
| Large files | No blob over 1 MB. Largest are `index.html` revisions (~0.8 MB). |
| **Shallow clone (critical)** | This repository is shallow (history only from 2026-10-26; boundary commits `9586b9e`, `a8b77fe`). **A normal push is rejected** ("shallow update not allowed"; reproduced against a local server) and GitLab.com cannot be set to accept it. Earlier history exists only on GitHub (and partly in the old Windows clone). |

## 2. Recommended approach (no force-push, nothing overwritten)
1. **Keep the shallow originals as they are** (they are in the backups). Make a *copy* in which the two boundary commits become root commits. File contents are unchanged: every branch tip has an **identical file tree** to the original (verified); only commit hashes change (a map old->new is kept; the two boundary commits lose their GPG signature).
2. **Production-equivalent `main`:** GitLab `main` is built from `origin/main` (`166ac63` content, what Render runs today), not the stale local `main`.
3. **GitLab's initial README commit** is joined with an ordinary merge commit (`--allow-unrelated-histories`), keeping our README. The result is a **fast-forward** for GitLab: no force, GitLab's commit stays in history. (Rehearsed on a throwaway server: conflict only on README, result tree identical to the prepared branch.)
4. Push `main` first, then the stage branches. Stage 30 reaches `main` later through a merge request after you approve it.
5. If GitHub returns: the rewritten history shares file contents but not hashes with GitHub, so the real full history would need a deliberate re-import. Keep the bundles in `Documents\Loominous-Backups`.
Alternative if you prefer to avoid a merge commit: push to a new branch name (e.g. `main-import`) and set it as GitLab's default branch in the project settings; the README-only `main` can then stay or be deleted by you.

## 3. Prepared package (built locally by `scripts/prepare_gitlab_import.sh`)
`loominous-gitlab-import.bundle` (non-shallow, only the prepared branches: `gl-main` plus the 6 stage branches; the stale local `main` is deliberately left out), `commit-map.txt`, `report.txt`. Credentials are never in it.

## 4. Exact steps on your Windows PC (after you approve; PowerShell, Git for Windows installed)
```powershell
$B = "C:\Users\tov\Documents\Loominous-Backups\gitlab-import"      # folder where you saved the 3 files (bundle, commit-map.txt, report.txt)
git init -b scratch C:\Users\tov\loominous-gitlab      # 'scratch' is just the unborn checked-out name, so the fetch below may create every branch
cd C:\Users\tov\loominous-gitlab
git fetch "$B\loominous-gitlab-import.bundle" "+refs/heads/*:refs/heads/*"
git checkout -q -B import-main gl-main           # prepared production-equivalent history ("import-main" is a local name only)
git remote add gitlab https://gitlab.com/loominous-group/loominous.git
git fetch gitlab                                  # sign in in the browser window GitLab/Git opens; never paste a token into chat
git log --oneline gitlab/main                     # expect one README commit
git merge --allow-unrelated-histories -m "Join GitLab initial commit" gitlab/main
#   If git reports conflicts ONLY in README.md (check: git status):
git checkout --ours README.md ; git add README.md
git commit -m "Join GitLab initial commit (keep project README)"
#   If it also lists other files (e.g. LICENSE, .gitignore), STOP and send me `git status`.
git diff --stat gl-main import-main               # must print nothing
git merge-base --is-ancestor gitlab/main import-main ; $LASTEXITCODE   # must be 0
git push gitlab import-main:main                  # plain push, no --force
git push gitlab stage-27c-consistency stage-27d-polish stage-28-auth-design stage-29-oauth-security stage-30-integration-prep stage-30-phase-b-prep
```
Then check on GitLab: `main` shows the project, 90+ commits; branch `stage-30-phase-b-prep` exists. In GitLab keep `main` **protected** (default), do not allow force-push.

## 5. Render (GitLab -> existing service)
Render docs confirm: Dashboard -> service -> Settings -> Build -> Source -> Edit lets you change the backing repository of an existing service (service type cannot change); Render connects GitLab under Account Settings -> Account Security -> Git Deployment Credentials; automatic deploys require **Maintainer or Owner** on the GitLab project; changing the source **triggers a deploy automatically**. Not stated by the docs, therefore **UNVERIFIED**: that the service URL and environment variables are unchanged. They are service settings, not repository properties, so I expect them to stay, but check `https://loom-phas.onrender.com` and the env list (names) right after.
Safe order: (1) migrate (section 4); (2) in Render switch Source to GitLab `loominous`, branch `main` (equals current production code, so the automatic deploy changes nothing functional); (3) verify the site and logs; (4) only then separately approve merging Stage 30 into `main` (GitLab merge request), which deploys the new design and Google code; (5) set the four Google variables when you decide. Before step 2, write down the current Render deploy ID and branch.
Other: GitHub Actions workflows (`.github/workflows/*`, tests and pilot) do not run on GitLab; a `.gitlab-ci.yml` is optional and not part of this migration. Cloudflare Pages is independent: if it is Git-connected to GitHub it will not receive updates either; see `LIVE_LAUNCH_PLAN.md` (Direct Upload).

## 6. Risks
Hash change vs GitHub (section 2.5); two unsigned root commits; GitLab's real initial commit unseen until you fetch; Render URL/env preservation unverified; mistaken push of `main` from the stale local branch (the prepared bundle avoids this: do not push the unprepared `main`).
