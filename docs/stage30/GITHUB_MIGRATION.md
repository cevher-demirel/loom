# Migration: GitLab back to GitHub

GitHub `main` (166ac63, Stage 27c) is a direct ancestor of everything in this branch. The migration is a
plain fast-forward-able history of 24 commits on top of it: nothing on GitHub is missing from here,
nothing here rewrites GitHub history, and `main` is untouched until the pull request is merged.

## What the PR brings over from GitLab
- Stages 27d, 28, 29 and 30 (Google sign-in code, disabled by default; additive migration; linking safety).
- The approved night-lake desktop and mobile login backgrounds (GitLab MR !2).
- The emotion flower label fix (compact flower 176px -> 200px, percentage 1.05rem).
- Docs under `docs/stage30/`, the migration rehearsal tools and the tests for all of the above.

## Deliberately not carried over
- GitLab MR !3 (`deploy-frontend` GitLab CI job): replaced by the Cloudflare plan below.
- The two GitLab-only housekeeping commits ("Initial commit", "Join GitLab initial commit"): they only
  added a README, identical in content to the one already on GitHub.
- `.gitlab-ci.yml` is still in the tree and inert on GitHub. Remove it in a later PR once GitLab is retired.

## Before merging (owner decisions)
Merging to `main` publishes whatever is connected to `main`: GitHub Pages (if still enabled) and Render
(if it is still linked to this GitHub repo). Check both in their dashboards first. The backend with Stage 30
is already deployed from GitLab; Google sign-in stays disabled until you decide otherwise.

## Reconnecting Cloudflare Pages
`loominous` is a Direct Upload project, and Cloudflare cannot switch such a project to Git. Options:

A. (Recommended) GitHub Actions deploys to the existing `loominous` project, so the domain and DNS never change.
   One workflow, triggered by hand (`workflow_dispatch`) on `main`, protected by a GitHub Environment
   `production` with you as required reviewer. Steps: checkout, `python3 scripts/build_frontend.py --out dist`,
   `npx wrangler@3.114.0 pages deploy dist --project-name=loominous --branch=main --commit-hash=$GITHUB_SHA`.
   Secrets (Environment secrets, not repo-wide): `CLOUDFLARE_API_TOKEN` (Account > Cloudflare Pages > Edit)
   and `CLOUDFLARE_ACCOUNT_ID`. The same token you created for GitLab can be reused.
   Add the workflow in its own PR so you review it separately.
B. Create a new Pages project connected to GitHub (build `python3 scripts/build_frontend.py --out dist`,
   output `dist`) and move loominous.org to it. Gives automatic deploys on every push to `main`, but the custom
   domain move carries brief risk and removes the manual approval gate.

## Retiring GitLab (later, only on your approval)
Keep GitLab read-only until the first GitHub-based deployment is verified, then archive (not delete) it and
revoke its tokens and the `CLOUDFLARE_*` GitLab variables.
