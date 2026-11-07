# Deployment audit (nothing was deployed or changed)

## What the repository shows
| Question | Finding |
|---|---|
| Hosting configuration files | None for Cloudflare Pages, Render or GitHub Pages: no `wrangler.toml`, `_headers`, `_redirects`, `render.yaml`, `CNAME`, `.nojekyll`. The only workflows are tests/pilot/preview (`.github/workflows`). |
| What the frontend needs | `index.html` plus `assets/login/login-mobile.webp` and `assets/login/login-desktop.webp`. All references are relative (`url("assets/login/…")`); no root-absolute paths, so root and subpath hosting both work (tested at `/` and `/loom/`). Fonts come from Google Fonts. |
| Are the assets tracked? | Yes: `git ls-files assets` lists both files (115 KB and 222 KB). |
| Backend URL used by the page | Hardcoded `https://loom-phas.onrender.com` (`API_BASE` in `index.html`). |

## Not verifiable from here (owner must check in the Cloudflare dashboard)
I could not read Cloudflare's current documentation from this session, and the dashboard settings exist only there. Do not assume them. Check:
1. **Source:** is the Pages project connected to the GitHub repository (blocked while the account is suspended) or deployed by direct upload?
2. **Branch** used for production and whether previews are enabled.
3. **Build command** and **build output directory.** If there is no build command and the output directory is the repo root, the host publishes **every tracked file**: backend `.py` source, `tests/`, `docs/` (including the security audits), `CLAUDE.md`. No secrets are tracked (`.env` and `loom.db` are git-ignored), but source and audit documents would be publicly downloadable. This was already the case with GitHub Pages.
4. **Root directory** setting, and that `assets/login/` appears in the deployed site (open `https://loominous.org/assets/login/login-desktop.webp`).
5. Custom domain `loominous.org` active, TLS valid.
6. That nothing in Cloudflare (Workers, rules, Access) rewrites paths or adds headers that affect `/assets/`.

## Option the repo now offers (owner's decision)
`python scripts/build_frontend.py` writes `dist/` containing exactly `index.html` and the two WebP files and fails on missing or root-absolute references (tested). Pointing Pages at it (build command `python scripts/build_frontend.py`, output directory `dist`) would publish only the page. Not configured by me.

## Render (backend)
- No `render.yaml`; `CLAUDE.md` states Render deploys the backend from `main`. Auto-deploy depends on GitHub access: blocked while suspended.
- Secrets are supplied as Render environment variables (names: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `PUBLIC_API_BASE`, `FRONTEND_URL`, plus existing ones). Nothing is committed.
- Render's free-instance documentation says free web services spin down after 15 minutes without traffic and take about a minute to start again, with a loading page in the browser. A first Google sign-in after idle will therefore feel slow or may time out at the start redirect. Flow records live in the database, so a restart in the middle of a flow does not break it, but rate-limit counters are in memory and reset on restart. Render also says free instances are not meant for production use.

## CORS and cookies with `loominous.org`
- API calls use `Authorization: Bearer …` with CORS `*`; no cookie is needed across sites.
- The only cookie is the OAuth binding cookie: set by the backend when the browser navigates to `/auth/google/start` (top-level navigation), sent back when Google redirects the browser to `/auth/google/callback` (top-level GET). `SameSite=Lax` allows exactly that and blocks cross-site forms and subrequests. It is host-only (no `Domain`), `Path=/auth`, 10 minutes, HttpOnly, Secure over https. The deletion re-authentication navigation works the same way.
- Compatibility with the topology is therefore **by design, not by loosening anything**: the binding is checked on the backend host that set the cookie, and the frontend never needs to read or send it. Verified locally in Chromium over http and self-signed https. **Not verified:** Safari/ITP behaviour, real iOS, real Google.

## Schema migration
Additive only (see `MIGRATION_SAFETY.md`). Production data was not read. The operator should run the preflight before the first deploy that contains it.

## Callback hostname: Option A (Render hostname) vs Option B (`api.loominous.org`)
Callback path from the code: **`/auth/google/callback`** (`oauth.redirect_uri`); full URI = `{PUBLIC_API_BASE}/auth/google/callback`.

| Topic | A: `https://loom-phas.onrender.com` | B: `https://api.loominous.org` |
|---|---|---|
| Google redirect URI rules (Google Cloud help, "authorized redirect URI" section) | https required; no raw IP; the top-level domain must be on the public suffix list (here `.com`); no wildcards or fragments; exact match. A Render hostname meets these. I found no Google rule rejecting `onrender.com`. | Same rules, met. |
| Authorized domains / ownership | Google says every domain used in the project must be registered as an authorized domain and that proving ownership (Search Console) is what allows a top-private domain. It does not say explicitly whether the redirect host must be one. You cannot verify ownership of `onrender.com`, so if Google insists, A fails at that point. **Unverified.** | `loominous.org` is yours: add as authorized domain, verify in Search Console, covers the `api.` subdomain. |
| TLS | Automatic, already working | Render issues and renews certificates automatically for custom domains |
| DNS | None | One CNAME record at the DNS provider for `api` pointing at the Render service (Render's domain page gives the target); remove conflicting AAAA records |
| Render support | Already live | Custom domains: Render's docs say free web services support them, and the pricing page lists 2 included on Hobby, `$0.25` per extra domain. Whether a free instance has any limit was not stated on the pricing page; confirm in the dashboard |
| Cookies / SameSite | Cross-site to `loominous.org`; fine for Lax top-level flow | Same-site with `loominous.org`; marginally more robust against browser cookie-partitioning changes, and opens the door to stricter settings later |
| CORS | `*` (bearer, no cookies) | Same; could be narrowed to `https://loominous.org` |
| Frontend change | none | `API_BASE` in `index.html` must change (and the temporary Render URL can stay as fallback) |
| Maintenance | Lowest | One more DNS record and domain to keep; independent of the Render hostname if the host is ever changed |
| Cost | none | none expected on a plan that includes custom domains (verify) |

**Recommendation: start with Option A for the Phase B live test.** It needs no DNS or Render changes and meets Google's documented redirect rules. Treat the authorized-domain question as the one thing to check in the console first (it is a 5-minute test). If the console refuses the Render host, or you want the API on your own domain for the public launch, move to Option B; nothing in the code is host-specific (`PUBLIC_API_BASE` and one `API_BASE` line).

Sources: Google Cloud Console Help, "Sign in with Google / OAuth 2.0 policies and restrictions" (support.google.com/cloud/answer/15549257); "Manage OAuth app branding" (support.google.com/cloud/answer/10311615); Render docs: Custom Domains, Free instance types, Pricing (render.com/docs/custom-domains, /docs/free, /pricing.md).
