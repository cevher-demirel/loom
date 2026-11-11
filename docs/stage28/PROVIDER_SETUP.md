# Google and Apple sign-in — setup

Nothing here is committed. Set these as environment variables on the backend host. Until they exist the buttons stay hidden and `/auth/<provider>/start` returns 404.

Common:
- `PUBLIC_API_BASE` — public backend URL, no trailing slash (e.g. `https://loom-phas.onrender.com`).
- `FRONTEND_URL` — already used for reset links (must be a full https URL, e.g. `https://loominous.org`; see `docs/stage29/GOOGLE_SETUP_GUIDE.md`). The callback sends people back here.
- Dependency `pyjwt[crypto]` (added to `requirements.txt`).

## Google
1. Google Cloud Console → APIs & Services → OAuth consent screen: set app name, support email, authorised domain, scopes `openid`, `email`, `profile`.
2. Credentials → Create OAuth client ID → **Web application**.
3. Authorised redirect URI: `${PUBLIC_API_BASE}/auth/google/callback` (exact match).
4. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
5. Publish the consent screen (production) before real users sign in.

## Apple
Requires a paid Apple Developer account.
1. Identifiers → create an **App ID** with Sign in with Apple enabled, then a **Services ID** (this is the client id). Enable Sign in with Apple on it.
2. Configure the Services ID: domain = backend host; return URL = `${PUBLIC_API_BASE}/auth/apple/callback`.
3. Keys → create a key with Sign in with Apple; download the `.p8` once.
4. Set `APPLE_CLIENT_ID` (Services ID), `APPLE_TEAM_ID`, `APPLE_KEY_ID`, and `APPLE_PRIVATE_KEY` (the `.p8` contents; `\n` escapes are accepted).
5. Apple posts the result to the callback (`form_post`); the backend already handles POST. Email may be a private-relay address and the name is only sent the first time.

## Before turning either on in production
- Decide the account-deletion path for provider-only accounts (AUTH_AUDIT risk 5).
- Test with a Google test user and an Apple sandbox account on a non-production backend first.
