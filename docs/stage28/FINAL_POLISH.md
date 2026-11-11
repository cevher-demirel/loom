# Stage 28 — final visual polish

Baseline `d288bb9` → this pass. Visual only: no change to endpoints, sessions, DOM IDs, validation, OAuth, linking or schema.

## Changes (index.html, tests/browser/test_stage28_login.py)
- **Mobile moon:** on screens narrower than 700px the card now sits in the lower part of the screen, and the portrait art is positioned at 35% horizontally (it is scaled to the phone's height, so only the sides are cropped). The moon, the mountains, the lake and the glowing portal all stay in frame. With no Google button (the live state) the card starts below the moon at 375×812, 390×844 and 430×932. With the Google button shown (taller card), 390×844 and 430×932 still clear the moon, 375×812 overlaps its lowest edge by about 8px, and 320×568 and 375×600 largely cover it.
- **Short screens:** at 568–600px tall the artwork is mostly behind the card. Usability wins over artwork there (the form must stay on screen), so the moon is largely hidden. This is a limit of the source image and the viewport, not something CSS can fix.
- **Spacing:** the "Don't have an account? Create an account" line is now a centred wrapping row with a 44px tap area that doesn't add layout height (padding grows the hit box, a negative margin gives the space back). The divider and Welcome Back margins are adjusted, and the card padding is tightened. At 320px the account line wraps onto two centred lines.
- **Desktop:** card width 420 → 460px (500px at 1700px and wider), padding 28×34, heading 2rem, wordmark 2.7rem. The landscape is still plainly visible around it.
- **Fallback:** if either WebP fails to load, the panel falls back to a dark gradient built from the app's own darks and the form is unaffected.

## Palette
Unchanged from visual kit v2: `--bg #0a0a1a`, `--surface #15132f`, `--surface-raised #1d1a44`, `--field-border #6a65b8`, `--accent #8f8aef`, `--text #ece9fb`. Sign In keeps the Home "Record a dream" gradient `#b79aff → #7d55f5 → #4f2ccf` with its `#e2d4ff` border and violet glow. This is the approved exception to the Stage 23g rule; no other button was changed.

## Asset packaging
- `assets/login/login-mobile.webp` (115,952 bytes, 936×1548) and `assets/login/login-desktop.webp` (222,404 bytes, 2370×1161) are tracked in git and not ignored.
- They are referenced with relative paths (`url("assets/login/…")`), which resolve both from `file://` and from a `/loom/` Pages subpath. A test guards against root-absolute paths.
- Breakpoint: portrait image under 700px, wide image from 700px (tested at 390 and 1280).
- Deployment: this repo has no Pages build/deploy workflow, so nothing lists files explicitly. If Pages publishes the branch root, as the existing root `background.png` suggests, `assets/` is included. **Could not be verified** because the GitHub account is suspended and Pages settings can't be read.
- Image quality: unchanged. The source files are soft at high pixel density; CSS cannot add resolution.

## Security blockers (report only; separate stage)
A. **OAuth login CSRF** — the callback must be bound to the browser that started sign-in (e.g. a signed, HttpOnly, short-lived cookie or a browser-held secret matched against `state`).
B. **Google-only account deletion** — accounts without a local password can't pass the current password check; they need a secure re-authentication path.
C. **Live Google sign-in** — never run end to end with real credentials.
These remain release blockers for turning Google sign-in on.
