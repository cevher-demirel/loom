# Cutover: Cloudflare Pages -> GitHub Pages (loominous.org)

Final layout: GitHub (code) / GitHub Pages (frontend, https://loominous.org) / Render (API, auth) / Turso (data).
Cloudflare may stay as DNS only.

## Findings (what was checked)
| Item | Finding |
|---|---|
| GitHub Pages | Publishes from the `main` branch automatically (`pages-build-deployment`; last run 2026-11-06 for 166ac63 at https://cevher-demirel.github.io/loom/). Merging PR #57 therefore republishes the Pages site at once. |
| What Pages publishes today | The whole repository root (backend source, tests, docs), not just the page. Fixed by the manual workflow in this branch (publishes `dist/` only). |
| Custom domain on GitHub | None in the repo (no `CNAME`). Pages API is not readable from this workspace: confirm in Settings > Pages. |
| Render | No `render.yaml`. `CLAUDE.md` says Render deploys from `main`. Render was last reconnected to GitLab, so its current source and auto-deploy setting are UNVERIFIED (dashboard only). |
| Cloudflare, DNS | Not reachable from this workspace (loominous.org and Cloudflare are not allowed). Current records, Pages custom domains and SSL mode are UNVERIFIED. |
| API URL | `API_BASE` is hardcoded `https://loom-phas.onrender.com`; CORS allows any origin; sign-in uses a bearer token, not cookies. A host change needs no backend change. |
| Google sign-in | Redirects use `PUBLIC_API_BASE` (Render) and return to `FRONTEND_URL`. Same domain, so nothing changes. Google stays disabled. |
| Direct navigation | One page (`index.html`), no client routes; links are `/?verify=` and `/?reset=` on the root, which work. Assets are relative, so the apex domain is fine. |
| Data safety | The frontend host has no access to Turso or accounts. No step below touches Render, Turso, users or dreams. |

## Unintended-deployment risks of merging PR #57
1. GitHub Pages republishes from `main` immediately: the new login art and Stage 30 frontend go live on the github.io site (and on loominous.org if that domain is already pointed at GitHub). Low risk: same page Cloudflare would serve; but it is a publish.
2. If Render is still linked to GitHub `main` with auto-deploy, it rebuilds the backend (Stage 30 is already deployed; the migration is additive and idempotent). Check Render > Settings > Build & Deploy first; turn auto-deploy off for the merge if unsure.
3. Pages currently serves backend source and docs from the repo root. Switch the Pages source to GitHub Actions (below) before or right after the merge.

## Safe sequence (each step waits for your approval)
1. Wait for CI on PR #57 to pass. Review. (No approval needed to wait.)
2. Owner: Render dashboard, confirm source/branch and auto-deploy; note the current deploy ID. Cloudflare dashboard, note the Pages deployment ID and screenshot the DNS records (rollback material).
3. Approve and merge PR #57. Pages republishes root (accepted risk 1).
4. Approve and merge the Pages-workflow PR (adds `pages-deploy.yml`; deploys nothing).
5. Owner: Settings > Pages > Source = "GitHub Actions". Run the workflow once on `main` ("Run workflow"). Check https://cevher-demirel.github.io/loom/ (page loads, login art, sign-in with a throwaway account only).
6. Owner: Settings > Pages > Custom domain = `loominous.org`; do not enable "enforce HTTPS" until the certificate is issued. Verify the domain under profile Settings > Pages (prevents takeover).
7. DNS (Cloudflare DNS, all of these as "DNS only", grey cloud, so GitHub can issue the certificate):
   - apex `loominous.org`: A 185.199.108.153, .109.153, .110.153, .111.153 (and AAAA 2606:50c0:8000::153 to 8003::153); remove the Cloudflare Pages apex record.
   - `www`: CNAME `cevher-demirel.github.io` (GitHub then redirects www to the apex).
   - Leave MX/TXT (email, support@loominous.org) untouched.
   Lower the TTL to 300s a day before. Expect minutes to an hour for propagation and certificate.
8. Verify: https://loominous.org and https://www.loominous.org load over HTTPS, redirects work, login art desktop/mobile, `/health` call from the page succeeds, sign-in and sign-up with a throwaway account, `/?verify=` and `/?reset=` links open the page. Then enable "Enforce HTTPS".
9. Only after a few days: remove the Cloudflare Pages custom-domain binding and (on your approval) the Pages project. Do not delete GitLab or Cloudflare resources earlier.

## Rollback
- Before step 7 nothing user-facing changed: stop.
- After step 7: put the Cloudflare DNS records back to the screenshot from step 2 (the `CNAME loominous.pages.dev` records), keep Cloudflare's Pages project and deployment until step 9. TTL 300s means recovery in minutes.
- A bad frontend build: re-run the workflow on the previous good commit, or revert the commit on `main`; the Cloudflare deployment stays available via Rollback until retired.
- Backend, Turso and accounts are never part of this change, so there is nothing to roll back there.
