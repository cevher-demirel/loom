# Stage 30: test report

Command: `python -m pytest -q -p no:cacheprovider` (whole repository, includes the Chromium browser tests), branch `stage-30-integration-prep`.
**Result: 944 passed, 0 failed, 0 skipped, 25m45s.** Stage 29 baseline: 906 passed. New: 38 tests.

| Group | Tests | Notes |
|---|---|---|
| `tests/test_oauth.py` | 70 (+4) | New: cookie has no `Domain` and is per-flow; cookie cleared by the callback; Secure follows https and is never dropped on https; a cookie outlasting its flow is useless |
| `tests/test_migration_safety.py` | 9 (new) | Synthetic databases; crash injected at every migration statement; duplicate identities; read-only preflight (counts only, byte-for-byte unchanged DB) |
| `tests/browser/test_stage30_interaction.py` | 17 (new) | Real `click()`/`tap()` only; regression for the inert-app bug (late animation frames); Settings → deletion prompt → cancel at 320, 375, 390, 430, 768, 1280, 1440, 1920 px; password deletion (wrong password keeps the account and is not treated as an expired session); Google-only deletion end to end (cancel at Google, verify, cancel after verifying, final click); wrong Google account; account with both methods; expired verification; expired session |
| `tests/browser/test_stage30_https_env.py` | 3 (new) | Self-signed https stack: Secure + HttpOnly + SameSite=Lax cookie works in Chromium and is cleared afterwards; seeded same-email account is offered linking, not merged; env script refuses to start with a production credential and never echoes it |
| `tests/browser/test_stage30_assets.py` | 5 (new) | Minimal build contains exactly `index.html` + the two login WebPs; artwork loads from `/` and `/loom/` at phone and desktop widths |
| `tests/browser/test_stage29_google_e2e.py` | 6 | `dispatch_event` workarounds removed; passed 3 consecutive runs and in the full suite |
| `tests/browser/test_stage28_login.py` | 34 | Login design and behaviour unchanged |

## Browser coverage
Chromium (headless, Playwright) only. Touch emulation (`has_touch`, `is_mobile`) below 900 px. **WebKit/Safari: not tested** (browser download blocked in the sandbox). **Real iPhone/Android and Firefox: not tested.**

## OAuth behaviour audit (what is covered, and where)
Cookie creation/expiry/attributes/scoping; cross-browser callback rejection (unit and real Chromium); PKCE S256 enforced by the mock provider; nonce, issuer, audience, expiry, signature, missing `sub`; state replay, concurrent callbacks, expiry; flow cleanup (consumed even on failure; deletion removes leftover flows); cancel and provider-error handling without leaking details; session creation, rotation, logout, expiry; Google-only deletion re-authentication. All against the mock; **none of it proves real Google behaves the same.**

## Limitations
- Mock provider, not Google. No test used a real credential, production database, Render, Cloudflare or Turso.
- A few Chromium-only details (hit testing, cookies) may differ in Safari.
- The two older feeling-wheel tests still use `force=True` on SVG paths (outside auth).
- Timing-sensitive UI bugs like the one fixed here are caught by forcing late animation frames; other timing races could exist.
- Cloudflare/Render configuration, callback-hostname acceptance by Google, and production data were not examined.
