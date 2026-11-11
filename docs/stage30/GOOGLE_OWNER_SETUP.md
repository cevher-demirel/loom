# Google Cloud setup: owner checklist

You do this yourself; nothing here has been done for you, and no Google project exists yet. **Never paste the client secret into chat, email, a ticket or a commit.** The secret goes only into the backend host's environment settings (Render) or a password manager.
Console labels change from time to time; I could not open the live console, so use the intent of each step if a label differs.

## Names taken from the code
| What | Value |
|---|---|
| Callback path | `/auth/google/callback` (`oauth.redirect_uri`) |
| Start path (not registered with Google) | `/auth/google/start` |
| Redirect URI to register | `{PUBLIC_API_BASE}/auth/google/callback`, e.g. `https://loom-phas.onrender.com/auth/google/callback` (Option A, see `DEPLOYMENT_AUDIT.md`) |
| Scopes the code requests | `openid email profile` |
| Backend environment variables | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `PUBLIC_API_BASE`, `FRONTEND_URL` |
| Frontend URL | `FRONTEND_URL=https://loominous.org` (full https URL, no trailing path, query or fragment) |
Google sign-in stays hidden until all four are valid; the backend logs an `oauth_config` line at start that lists problem **names** only.

## A. Local testing (no Google account needed)
Use `scripts/oauth_test_env.py` (see `INTEGRATION_TEST_ENV.md`). It uses a mock provider and placeholder credentials; do not put real Google credentials into it.

## B. Real Google, isolated test (Phase B, only after review)
Run a **separate** backend and **separate** throwaway database for this, never the production database. A second Render service with its own empty database is the safest. Use a dedicated Google test account and a separate Loominous test account.
1. Sign in at console.cloud.google.com with an existing Google account (preferably a dedicated owner account for Loominous).
2. Create a new project (name e.g. `loominous-auth`) or select a dedicated one. Do not reuse an unrelated project.
3. Open **Google Auth Platform** and complete the setup: app name `Loominous`, user support email, contact email.
4. **Branding:** home page `https://loominous.org`; add privacy policy and terms links if you have them (needed before production). **Authorized domains:** add `loominous.org`. Google states that every domain used in the project must be an authorized domain; if you also register the Render host and the console refuses it, note that and see `DEPLOYMENT_AUDIT.md` (Option B).
5. **Audience:** choose **External**. Leave publishing status **Testing**. Add your dedicated test Google account under **Test users**. Only listed accounts can sign in while in Testing.
6. **Data access:** the app needs only `openid`, `email` and `profile` (the non-sensitive set). Do not add other scopes.
7. **Clients → Create client → Application type: Web application**, name `loominous-test`. Leave **Authorized JavaScript origins** empty (the browser never calls Google directly; the backend does the exchange). Under **Authorized redirect URIs** add exactly `https://<test-backend-host>/auth/google/callback` (character for character: https, no trailing slash, no wildcard). Google says changes can take from about 5 minutes to a few hours to apply.
8. Create. Copy the **Client ID** and **Client secret** straight into the test backend's environment variables (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`). If the console will not show the secret again, create a new secret instead of recovering it from anywhere.
9. On the test backend also set `PUBLIC_API_BASE=https://<test-backend-host>` and `FRONTEND_URL=<the test frontend origin>`; redeploy; confirm the startup log's `oauth_config` shows no problems and `/auth/providers` reports google as available.
10. Expected behaviour: **Continue with Google** goes to `accounts.google.com`, you pick the test account (and consent the first time), Google redirects to `/auth/google/callback`, the backend redirects to the frontend and you land signed in; the address bar contains no code or token afterwards. Cancel at Google returns you to Sign In with a message and no account. Account deletion for a Google-only account shows **Verify with Google**, Google asks you to sign in again, then a separate **Permanently delete my account** button appears.
11. Work through `RELEASE_GATES.md` (live checklist), including mobile and Safari.

## C. Future production (not now)
- Use a **new** OAuth client (or a deliberate production one) with the production redirect URI; keep the test client for testing.
- Publishing status **In production** makes sign-in available to every Google user. Google requires a homepage and privacy policy link for external production apps and verification of brand assets if you want your name and logo on the consent screen; whether the basic scopes need further review should be confirmed in the console at that time. Verify domain ownership in Google Search Console for `loominous.org`.
- Rotate the secret if it is ever exposed. Do not commit it; do not log it (the backend never logs it).
- Owner decision: enabling this for real users is a separate approval and is not part of Stage 30.

## What you should never be asked to do
Send a client secret, an access token, an authorization code, a database export or a user's data to anyone. If a step seems to need that, stop and ask.
