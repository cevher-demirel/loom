# Isolated Google sign-in test environment

Everything runs on this machine, on loopback. It uses the **real** `index.html` and the **real** FastAPI app, a throwaway SQLite file, and a local mock OpenID Connect provider (`tests/mock_idp.py`). It never contacts Google, Render, Turso, Pinecone or Resend and needs no secret.

## Start / stop
```bash
python scripts/oauth_test_env.py            # http on 127.0.0.1 (Secure flag off: loopback only)
python scripts/oauth_test_env.py --https    # self-signed https: the Secure cookie behaves as in production
python scripts/oauth_test_env.py --seed     # also creates synthetic password user dreamer / Moonlit9pond
```
It prints the frontend, backend and mock-provider URLs and the test database path. Open the frontend URL, click **Continue with Google**. The mock provider approves automatically as `dreamer@example.test`; with `--seed` that email belongs to the seeded password account, so you will see the link-account screen (correct behaviour: no email-only merge). Without `--seed` a new Google-only account is created.
Stop with **Ctrl+C**: the test database, temporary site and any throwaway certificate are deleted. Nothing else is written.

With `--https`, the browser shows a certificate warning (self-signed, valid for 127.0.0.1 for one day, generated in the temp folder, never committed). Accept it, or use a browser started with certificate errors ignored. Production cookie settings are not changed for any of this; http mode only works because `oauth.py` allows http for loopback hosts.

## Safety guards (fail closed)
- Refuses to start if any of `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `PINECONE_API_KEY`, `RESEND_API_KEY` is set (the value is never printed).
- Forces `USE_TURSO = False`; uses only a file named `loom_stage30_test_<pid>.db` in a fresh temp directory.
- Google client id/secret are placeholders held in process memory only.
- `tests/browser/test_stage30_https_env.py` checks both the https behaviour and the refusal.

## Automated use
`from scripts.oauth_test_env import Stack` gives tests the same stack (`Stack(https=True, seed=True)`, `.api`, `.front`, `.idp`, `.close()`). The Stage 29 and 30 browser tests use an equivalent pytest fixture.

## Run the browser suites
```bash
pytest tests/browser/test_stage29_google_e2e.py tests/browser/test_stage30_interaction.py \
       tests/browser/test_stage30_https_env.py tests/browser/test_stage30_assets.py
```
Requires Playwright + Chromium (`REQUIRE_BROWSER=1` makes a missing browser a failure). WebKit could not be installed in the build sandbox.

## Limits
This proves protocol handling and wiring with a mock. It does not exercise real Google, real Render/Cloudflare networking, Safari, or real devices.
