# Stage 29 — Test report

Command: `python -m pytest -q -p no:cacheprovider` (whole repo, includes browser tests) on branch `stage-29-oauth-security`.
**Result: 906 passed, 0 failed, 0 skipped, 23m08s.** Baseline before this stage: 864 passed.

| Group | Count | Notes |
|---|---|---|
| `tests/test_oauth.py` | 66 | Real local mock IdP over HTTP, real RS256 signatures, PKCE enforced by the provider, each "browser" has its own cookie jar |
| `tests/browser/test_stage29_google_e2e.py` | 6 | Real `index.html` + real FastAPI (uvicorn thread) + mock IdP in Chromium: button hidden until configured, full login, cancel, other-browser callback rejected, Google-only deletion end to end, deletion cancelled at Google |
| `tests/browser/test_stage28_login.py` | 34 | Still pass after the UI edits |
| Everything else | unchanged | Password/signup/reset regressions covered |

Covered scenarios (the 30 requested): valid and cancelled login; missing, wrong, expired and altered state; replay; wrong browser; missing and modified cookie; invalid PKCE verifier; wrong issuer/audience; expired token; bad signature; wrong nonce; reused identity; existing unlinked email; unverified email; repeated login; concurrent linking and sign-in; Google-only deletion; deletion with a different Google identity; expired and replayed deletion authorization; deletion cancel; logout and session invalidation; email/password and reset regression; no production DB access; no tokens or secrets in logs.

## Not performed / limitations
- **No test against real Google.** All provider behaviour is a mock; passing here does not prove live Google works.
- Chromium only. Safari, iOS, Firefox not tested.
- In the e2e browser tests a few clicks on Settings/delete controls use `dispatch_event("click")` because Playwright's hit-test reported the page body over the controls in the test harness; the UI itself rendered and was checked by screenshot.
- Controlled clocks are used for expiry tests; no real waiting.
- No deployment, Cloudflare, Render or Turso checks were possible.
