# Google sign-in: owner-only testing switch

Google sign-in stays restricted until the owner sets `GOOGLE_SIGNIN_MODE=public` on the backend.
Anything else, including the variable being missing, means restricted (it fails closed).

## Server settings (Render environment; never in code, never in the frontend)
| Variable | Purpose |
|---|---|
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Existing. The secret is entered only by the owner, in Render. |
| `PUBLIC_API_BASE`, `FRONTEND_URL` | Existing. `https://loom-phas.onrender.com` and `https://loominous.org`. |
| `GOOGLE_TEST_KEY` | A long random string (24+ characters) that only the owner knows. |
| `GOOGLE_TEST_EMAILS` | Comma-separated Google emails allowed during testing. |
| `GOOGLE_SIGNIN_MODE` | Leave unset (or `test`) while testing. `public` opens it to everyone. |

## What restricted mode does
1. **Hidden:** `GET /auth/providers` reports Google only to a caller who sends `GOOGLE_TEST_KEY` in the
   `X-Google-Test-Key` header. Ordinary visitors get `google: false`, so the button never renders.
2. **Cannot be started:** `/auth/google/start` needs a one-time ticket from `POST /auth/google/test-start`,
   which needs the key. The key is never placed in a URL (it is typed into a password box). Without the key the endpoints answer 404.
3. **Callback is restricted too:** after Google's token is verified, the verified email must be in
   `GOOGLE_TEST_EMAILS`, otherwise the flow stops with `not_allowed` before anything is created, linked or
   signed in. Account linking still needs the existing account's password.
4. Email and password sign-in, accounts and dreams are not touched.

## How the owner opens it
Open `https://loominous.org/#owner` (no secret in it). A small "Owner key" password box appears under the
sign-in form; paste `GOOGLE_TEST_KEY` from your password manager and press Unlock. The key is never in a URL,
history, logs or the page code; it is kept for that browser tab only (sessionStorage) and sent as a header.
Closing the tab forgets it. Old-style `#google_test=<key>` links no longer do anything.

## Going public (owner's decision) and rollback
Set `GOOGLE_SIGNIN_MODE=public` and redeploy to open it. To close it again, remove that variable.
