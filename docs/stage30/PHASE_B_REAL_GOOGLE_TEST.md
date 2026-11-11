# Phase B: real-Google test on an isolated local backend

Status: **prepared, not run.** Nothing here touches the Loominous production backend, Render, Turso, or DNS, and no credential is stored anywhere.

## 1. Decision: use a local HTTPS callback; no temporary public hostname
Google's redirect-URI rules (Google Cloud Help, "authorized redirect URI") require https **except for localhost**, and say localhost URIs "including localhost IP addresses" are exempt from the HTTPS and IP-host rules. So a callback on the tester's own machine is allowed. It needs no tunnel, no extra download, no public exposure and no second Render service, all of which add risk. A temporary public hostname is therefore **not needed**.

The test runs `scripts/oauth_test_env.py --https --real-google` on **your Windows PC**, because Google redirects *your browser* to the callback and only your PC can answer `localhost`. (The cloud session cannot receive that redirect, and I cannot see your browser or type your secret.)

| | Address | Why |
|---|---|---|
| Backend | `https://localhost:8444` | the callback host Google redirects to |
| Frontend | `https://127.0.0.1:8443` | a different *site* from `localhost`, like loominous.org vs the Render host, so the cross-site cookie behaviour is realistic |
| **Redirect URI to register** | **`https://localhost:8444/auth/google/callback`** | exact path from the code (`/auth/google/callback`) |

Self-signed certificate (generated at start, deleted at exit, never trusted system-wide; no change to Windows security settings).

## 2. Google Cloud: what to add
**Recommended: a second OAuth client for testing only** (Google Auth Platform → Clients → Create client → Web application, name `loominous-local-test`).
- Authorized redirect URI: `https://localhost:8444/auth/google/callback` and nothing else.
- Authorized JavaScript origins: leave empty.
- Leave the existing client and its Render URI (`https://loom-phas.onrender.com/auth/google/callback`) exactly as they are.
- Why a second client: the test secret then never sits next to the production URI; you can delete the test client afterwards without touching anything else.
- Your account is already a test user and the app stays in **Testing**: keep it that way.
Google may take from about 5 minutes to a few hours to apply a new redirect URI.
(Adding the localhost URI to the existing client would also work, but mixes test and production configuration. Not recommended.)

## 3. Entering the client ID and secret (never in chat)
The script asks for them at a **hidden prompt** (`getpass`: nothing is echoed). They are held only in that Python process, never written to a file, never put in the command line or environment, never printed or logged (the backend never logs them). The script refuses to start if `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `PUBLIC_API_BASE` or `FRONTEND_URL` is already set in your shell, or if any Turso/Pinecone/Resend credential is present. Do not run `Start-Transcript`, and paste the values only at the prompt.

## 4. Exact steps (PowerShell)
```powershell
# 1. Get the code into a NEW folder (not the OneDrive folder, not the old clone)
Expand-Archive "$HOME\Downloads\loominous-phase-b-kit.zip" "$HOME\Documents\Loominous-PhaseB-Test"
cd "$HOME\Documents\Loominous-PhaseB-Test\loominous-phase-b"
# 2. Fresh virtual environment inside that folder (do not reuse the old venv)
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# 3. Start the isolated environment against real Google
python scripts\oauth_test_env.py --https --real-google
#    -> prints the redirect URI, asks you to type YES, then asks for the ID and secret (hidden)
# 4. In Chrome: open https://localhost:8444/auth/providers once, choose Advanced > Proceed (self-signed certificate).
#    Expect {"google":true,...}. Then open https://127.0.0.1:8443/ and accept its warning too.
```
Stop with **Ctrl+C**; the test database, certificate and temp site are deleted ("stopped; test data deleted").

## 5. Test checklist (expected results)
1. Press **Continue with Google** → Google account chooser/consent (a "Google hasn't verified this app" screen may appear for a test app; continue) → you return signed in; the address bar has no code or token.
2. Sign out, sign in again → same account, no duplicate.
3. Start sign-in, press **Cancel/Back** at Google → Sign In with a message, no session.
4. **Other-browser rejection:** start sign-in in Chrome, and *at the Google screen copy the address-bar URL*, open it in a Private/other-browser window, approve there → rejected at the callback (no binding cookie); nothing signed in.
5. Reload the final callback URL (browser Back, then forward) → rejected (single use).
6. Account deletion: Settings → Account → Delete → **Verify with Google** → Google asks you to sign in again → **Permanently delete my account**. Only the throwaway local account is deleted, never your Google account.
7. Linking: before step 1, sign up a *password* account in the app using your Google email, then press Google → link screen; wrong password rejected, right password links.
8. Optional (needs a second test user): delete with a *different* Google account → "isn't the Google account linked to this account", nothing deleted.
Watch the terminal: no `code=`, `state=`, token or secret should appear.

## 6. Risks and how they are contained
| Risk | Containment |
|---|---|
| Touching production | The backend runs only on your PC, loopback only, with a throwaway SQLite file; the script refuses if any production credential or public URL variable is set; the production redirect URI is not used and the Render service is not involved. I cannot verify what the live Render service currently runs (nothing from Stages 28–30 was deployed from here). |
| Secret leakage | Hidden prompt, memory only, not logged; delete or rotate the test client secret afterwards. |
| Real personal data in the test database (your Google email, name, `sub`) | Stored only in the temp database, deleted on exit. If the window is killed abruptly the printed `Test DB` path can be deleted by hand. |
| Browser certificate warnings | Self-signed, loopback-only; expected. Not tested in Safari. |
| Google applying the redirect URI late | Wait and retry; `redirect_uri_mismatch` means the URI differs or has not propagated. |
| Cookies | Chrome only; Safari/iOS still untested. |
| Port clash (8443/8444 in use) | Use `--api-port` / `--front-port`; then register the matching redirect URI instead. |

## 7. After the test
Ctrl+C; confirm the temp folder is gone; revoke the app at myaccount.google.com → Security → third-party access; delete the `loominous-local-test` client (or delete its secret). Send me the *observations only* (what you saw, any error text with codes removed), never codes, tokens or secrets.

## 8. Not covered
Production behaviour, Cloudflare/Render networking, Safari/iOS, cold starts, real-device behaviour, Google "In production" status.
