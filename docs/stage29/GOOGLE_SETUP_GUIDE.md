# Google sign-in setup for `loominous.org`

Do not paste secrets into chat, tickets or commits. Secrets go only into the Render environment (or a secret manager). This guide changes nothing by itself.

## Values taken from the code
- Callback path: `/auth/google/callback`, mounted on the **backend**. Redirect URI = `{PUBLIC_API_BASE}/auth/google/callback` (`oauth.redirect_uri`). The frontend currently calls `https://loom-phas.onrender.com`, so with that backend the URI is `https://loom-phas.onrender.com/auth/google/callback`. It must match character for character (scheme, host, no trailing slash).
- After sign-in the backend redirects to `{FRONTEND_URL}/#…`, so `FRONTEND_URL=https://loominous.org`.
- Scopes requested: `openid email profile`. Google's own sign-in page is reached by browser redirect, so **no "Authorized JavaScript origins" are needed**.

## Environment variables (backend only)
| Name | Value |
|---|---|
| `GOOGLE_CLIENT_ID` | from Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | from Google Cloud Console (secret) |
| `PUBLIC_API_BASE` | public backend URL, https, no trailing slash, no query/fragment |
| `FRONTEND_URL` | `https://loominous.org` (https, no query/fragment) |

Google stays hidden until all four are valid. Check startup logs for the `oauth_config` event: it lists problem **names** only, never values. `http` is accepted only for `localhost`, `127.0.0.1`, `[::1]` and `*.localhost` (local development).

## Console steps
1. Create or choose a Google Cloud project for Loominous.
2. APIs & Services → OAuth consent screen. User type External. App name, support email, developer contact email.
3. Authorized domains: add `loominous.org`. Home page `https://loominous.org`; add privacy policy and terms links if the console requires them.
4. Scopes: only `openid`, `email`, `profile` (non-sensitive, so no sensitive-scope review).
5. **Testing mode** (default): only listed test users can sign in, up to 100; refresh behaviour is irrelevant here. Add the dedicated test Google account as a test user. Moving to **In production** makes it open to every Google user and may require brand/domain verification. That step is an owner decision and must not happen until the live test checklist passes.
6. Credentials → Create credentials → OAuth client ID → **Web application**. Add the authorized redirect URI above. Leave JavaScript origins empty.
7. Domain verification: Google asks you to prove ownership of authorized domains (Search Console, DNS TXT). Needs access to `loominous.org` DNS.
8. Put the client id/secret into Render environment variables, redeploy, and confirm the `oauth_config` startup event shows no problems.

## Open question (needs owner decision)
The callback host is the Render hostname (`onrender.com`). Google's authorized-domain checks apply to the consent-screen domains; I could not verify against Google whether a Render hostname is accepted as the redirect host for a production consent screen. If the console objects, the clean fix is a custom domain for the API (for example `api.loominous.org` on Render), then set `PUBLIC_API_BASE` accordingly and register that redirect URI. The frontend's hardcoded API URL would need the same change. Not assumed or done here.

## Live testing (safe procedure)
Use a **non-production** backend and database (local or a separate Render service with its own throwaway Turso database), a dedicated test Google account, and a separate Loominous test account. See `RELEASE_READINESS.md` for the checklist.
