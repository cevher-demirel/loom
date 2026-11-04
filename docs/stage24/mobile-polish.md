# Stage 24e — mobile polish and wording

- Emotion wheel centre label and legend now use the same display name as the rest of the app (Joy → Happy). Display only; emotion IDs are unchanged.
- Element screen Back button raised to a 48px minimum height (was 39px). Found by the new viewport sweep.
- `tests/browser/test_stage24e_mobile.py` checks Dream Detail and the element screen at 320x568, 375x667, 390x844, 430x932, 768x1024, 1280x800 and 844x390 for horizontal overflow and tap targets.
- Harness: `LOOM_INDEX_HTML` env var points the browser tests at another index.html (used for before/after screenshots).
- Not tested: real Safari/iOS (Chromium emulation only).
