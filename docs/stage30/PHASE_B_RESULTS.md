# Stage 30 Phase B: real-Google test results and follow-up

Environment of the manual test (run by the owner on Windows): frontend `https://127.0.0.1:8443/`, backend `https://localhost:8444`, OAuth client `loominous-local-test`, temporary local SQLite database. No production deployment, database or credential was involved.

## What the real Google test showed (owner-reported, not reproduced by me)
| Item | Result |
|---|---|
| Google authentication completes | Confirmed |
| Redirect back to the app on `https://127.0.0.1:8443/` | Confirmed (cross-site frontend/backend, Secure cookie, Lax) |
| Authenticated Home loads with the username | Confirmed |
| Logout returns to the login page | Confirmed |
| Signing in again with the same Google account | Confirmed (identity reused; no sign of a duplicate, but the database was not inspected) |
| Earlier `401: invalid_client` | **Cause not established.** See below. |
| Ctrl+C did not stop the script | Cause identified, fix verified on Linux; **needs one confirmation on Windows**. See below. |

## Shutdown and cleanup
**Leftovers found.** Listing the names in `C:\Users\tov\AppData\Local\Temp` showed two folders, `loom_stage30_env_a5r6derf` and `loom_stage30_env_elxee448` (two runs: the failed and the successful one). So cleanup **did not complete**. Each holds the throwaway database (which contains your Google email, name and account ID), a throwaway self-signed certificate and its private key, and a temp copy of the page. They are not connected to production, but delete them:
```powershell
Get-ChildItem $env:TEMP -Directory -Filter 'loom_stage30_env_*' | Remove-Item -Recurse -Force
```
(or, with the updated script: `python scripts\oauth_test_env.py --cleanup`, which lists the folders and deletes only recognised ones after you type DELETE).

**Why Ctrl+C was unresponsive (probable root cause).** The script waited with `threading.Event().wait()` and no timeout. On Windows an untimed wait on a lock is not interrupted by Ctrl+C (a known CPython limitation), so the `KeyboardInterrupt` never ran and the cleanup in the `finally` block never started. I could not reproduce on Windows from here (the cloud environment is Linux), so this is a strong diagnosis, not an observation.
**Fixes (`scripts/oauth_test_env.py`):**
- The wait is now a loop of `sleep(0.25)` calls with explicit SIGINT, SIGTERM and Windows SIGBREAK handlers.
- Cleanup also runs from `atexit`; `close()` retries deletion (Windows can hold files briefly) and **reports whether the folder is really gone**, telling you the path and the `--cleanup` command if not.
- A marker file, plus `--cleanup`, finds leftovers of runs that were killed (for example by closing the window, which no Python code can intercept).
**Verified here:** SIGINT and SIGTERM stop the script within seconds and delete everything; the polling design is checked; `--cleanup` removes only recognised folders (a look-alike decoy survived); `close()` returns False if deletion fails. **Not verified:** a real Ctrl+C in Windows PowerShell. Please try once with the mock mode (`python scripts\oauth_test_env.py --https`).

## The earlier `401: invalid_client`
Two different places can produce it, and I can't tell which one you saw:
1. **On Google's own page** (before sign-in) as "Error 401: invalid_client": the client ID was not found, usually a mistyped or truncated ID, an ID from another project/client, or a client that was just created and has not propagated yet.
2. **After returning to Loominous** (shown as a generic provider error): Google refused the code exchange because the client ID and secret did not match: a mistyped secret, a secret pasted with quotes or spaces, a secret from a different client, or an old secret that was replaced.
Both would clear on a retry with correct input, and a retry succeeded, which fits a typo or propagation delay, but I cannot confirm that.
**What I changed so it is diagnosable next time (no secrets involved):**
- The script now checks the pasted values for common mistakes (quotes, spaces, wrong shape, missing `GOCSPX-` prefix) without echoing them.
- In real mode it makes one harmless call to Google's token endpoint with a deliberately invalid code. `invalid_client` means the ID/secret pair is wrong ("Google rejected…, check…"); any other answer means the pair is accepted. It then tells you before starting.
- The backend now logs why a code exchange failed: only the HTTP status and Google's short `error` code (e.g. `invalid_client`, `invalid_grant`, `redirect_uri_mismatch`), never the description, code, secret or response body.

## Security findings from this review
**Added: `auth_time` check for deletion proofs.** Deletion asks Google for `prompt=login&max_age=0`. If Google's ID token reports `auth_time`, it must now be within 5 minutes (60 s clock skew allowed), otherwise the proof is refused (`reauth_stale`, account untouched). If Google omits the claim it is accepted (the request itself demanded a fresh login) and a log line records `auth_time_present: true/false`. **Real Google has not yet been observed for this flow**, so that log line is how the next live test will show what Google actually sends. If it shows `false`, the decision is whether to keep accepting (current) or to require a fresh-login prompt by other means.

## Verification gaps still open (real Google)
1. Account deletion with "Verify with Google" (including that `prompt=login` forces a password/choice screen, and `auth_time`).
2. Cancel at Google (consent screen Cancel / Back).
3. Other-browser rejection with real Google (copy the Google URL into a private window).
4. Callback replay with real Google.
5. Linking an existing password account that has the same email.
6. Wrong Google account at deletion (needs a second test user).
7. Persistence checked against the real database: the temp database is deleted at exit, so persistence is shown by automated tests only (below), not by inspecting the live run.
8. Safari, iPhone, Firefox, and the Windows Ctrl+C confirmation.

## Automated coverage added in this phase (mock Google, isolated database)
- Account and identity persist across three simulated server restarts; no duplicate users or identities; dreams survive.
- A password account linked to Google stays one account with one identity after a restart, and password login still works.
- Stale `auth_time` refused, fresh accepted, missing logged; token-failure logging records only status and a plain error code (and drops a non-plain one); no secret text appears.
- The harness fixes above.
Linking, duplicate prevention, replay, wrong-browser, wrong-account, expiry and concurrency cases from Phases A and 29 remain in `tests/test_oauth.py`.
