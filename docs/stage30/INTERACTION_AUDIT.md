# Stage 30 — Interaction audit (the "body intercepts pointer events" problem)

## Verdict: **C — a genuine UI bug that the test harness made visible**
Stage 29 worked around it with `dispatch_event("click")`. That was hiding a real defect, so those workarounds are removed.

## Root cause
`openAuthOverlay()` schedules two nested `requestAnimationFrame` callbacks that, on the second frame, add the classes `open` (overlay) and `auth-overlay-open` to `#app-shell`. `#app-shell.auth-overlay-open { pointer-events: none }` (the app is intentionally inert while the sign-in sheet covers it).

`closeAuthOverlay()` removes those classes, but **did not cancel the pending frames**. If sign-in finishes before those two frames have run (a very fast response, or a busy / background tab where frames arrive late), the sequence is: open → close (classes removed) → stale frames fire → `auth-overlay-open` is added back with no overlay left to dismiss. `#app-shell` then has `pointer-events: none` for good: every Settings, Journal and deletion control looks normal in screenshots but cannot be clicked, and Playwright reports `<body> intercepts pointer events`.

It showed up in the Stage 29 browser tests because the local backend answers in ~25 ms, faster than two frames, so it was intermittent (about 1 run in 4). A real user needs a fast response plus a late frame: rare, but possible (for example returning from Google in a tab that was in the background), and the effect is a dead app until reload.

## Evidence
- Deterministic reproduction: delay animation frames by 400 ms (`slow_frames` in `tests/browser/test_stage30_interaction.py`), sign in with Google, then click Settings.
  - Stage 29 `index.html`: `#app-shell` class `shell auth-overlay-open`, computed `pointer-events: none`, real click blocked (`<body> intercepts pointer events`).
  - Stage 30 `index.html`: class `shell`, `pointer-events: auto`, click works.
- Playwright traces and screenshots of both runs: `evidence/before-stage29-index-trace.zip`, `evidence/after-stage30-index-trace.zip` (view with `playwright show-trace`).
- Ruled out: stacking contexts, z-index, bottom sheets, scroll position, splash fade (the splash is `display:none` / `pointer-events:none` after its fade), desktop vs mobile layout, test setup. `elementsFromPoint` at the control showed `BODY, HTML` only, which isolated the inert `#app-shell`.

## Fix (smallest safe change, `index.html`)
An epoch counter: `openAuthOverlay` records `++authOverlayEpoch` and its frame callbacks do nothing if the epoch has changed; `closeAuthOverlay` increments it. 8 lines, no visual change.

## Test changes
- All `dispatch_event` workarounds removed; no `force=True` is used anywhere in the new tests. Controls are reached with `click()` (desktop) or `tap()` (touch devices).
- Pre-existing `force=True` remains in two older feeling-wheel tests (`harness.py`, `test_stage23a_recording_mobile.py`) on SVG paths. These are outside the auth flow and were not touched; they are listed as a known weakness in `RELEASE_GATES.md`.

## Flows verified with real pointer input (synthetic accounts, mock Google, local backend)
Open Settings → Account → deletion prompt; start Google re-authentication; cancel at Google; return to the account screen; cancel after verifying; final deletion; password-account deletion (wrong password keeps the account and does not look like an expired session); wrong Google account; expired verification; expired session; account with both methods.
Widths: 320, 375, 390, 430, 768, 1280, 1440, 1920 (Settings → deletion prompt → cancel). Touch `tap()` is used below 900 px with `has_touch` and `is_mobile` emulation. **Real devices and WebKit/Safari were not tested.**

## Navigation note (not changed)
On a phone the Home view has no header, so the Settings gear is reached from the Journal tab (the header gear appears on the other tabs). That is the approved design; tests follow the same path a person would.
