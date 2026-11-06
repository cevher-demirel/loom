# Stage 27b — Accessibility, readability and touch targets

CSS plus one small pure-colour helper. No layout, navigation, data, backend or Loom Map relationship changes.
Source: Stage 26 audit findings F-02, F-03, F-04, F-14.

## What changed

| Area | Change |
|---|---|
| Form field borders (F-04) | New token `--field-border: #6a65b8` used by `.text-input` and `textarea` (Sign In, Sign Up, Forgot, Reset, Profile, Account, composer fields). Fill, radius, padding, focus glow unchanged. |
| Journal pills (F-14) | `pillTextColor(c)`: pill text is lightened toward white only as far as needed for 4.6:1 against the pill's own tinted fill over `--surface`. Fill stays `colour @ 10%`, border `colour @ 40%` (was 20%). Colour families unchanged. |
| Hit areas (F-02, F-03) | Reused the Stage 23b invisible `::after` hit-area pattern. Added: `.more-toggle` ("Show more"), `#loom-graph-view-list-btn` ("View List"), `.dream-screen-back`, `.primary-btn/.secondary-btn` (4→5px), `#dream-screen-edit-date-btn`. Edit/Delete gap 2px → 12px so each keeps a 44px area without overlap. Visible icons are not enlarged. |
| Focus rings | Small text-style controls that fell back to the thin browser default now use the app's `--focus-ring` (2px accent). |

Most small controls already had 44px hit areas from Stage 23b; the Stage 26 audit measured their *visible* boxes (28–38px). 27b measures real hit areas with `elementFromPoint`.

## Measurements

Contrast (WCAG formula, computed in the browser from rendered styles):

| Item | Before | After | Need |
|---|---|---|---|
| Input border vs card (worst gradient stop) | 1.62 : 1 | 3.35 : 1 | 3 : 1 (1.4.11) |
| Input border vs field fill | 1.49 : 1 | 3.57 : 1 | 3 : 1 |
| Worst emotion pill text (all 16 emotions + 20 tag pills) | 3.67 : 1 ("curious", Stage 26 audit); 4.33 : 1 (Aggressiveness, first failing pill in the 27b test) | 5.12 : 1 | 4.5 : 1 (1.4.3) |

Hit areas at 320 and 390 px (width × height, CSS px):

| Control | Visible | Hit before | Hit after |
|---|---|---|---|
| Dream Detail Edit | 32×32 | 34×46 (squeezed by Delete) | 44×44 |
| Dream Detail Delete | 32×32 | 34×46 | 44×44 |
| Dream Detail "Show more" | 91×19 | 92×20 | ≥43 high (asserted by test) |
| Map "View List" | 56×18 | 58×20 | 58+12 × 44 |
| Dream Detail back bar | 390×40 | 390×40 | 390×44 |
| Log out | 83×36 | 84×42 | 84×44 |
| Date/place edit | 32×32 | 46×42 | ≥43×43 (asserted by test) |

All other audited controls (gear, back, filter chips, Map view toggles, filter, zoom, close, Home search/links, "Review in Loom Map") already measured ≥44 and are asserted by the tests.

## Remaining limitations

- Map nodes at 320 px are dense by design (27×32 visible). Neighbouring node hit areas touch; we meet WCAG 2.5.8 (24px) via spacing but not the 44px recommendation. Changing node layout would change graph presentation and is out of scope.
- Desktop side-nav buttons are 40px high (≥24, AA); not enlarged.
- Verified in Chromium only; no real iOS/Safari device. Synthetic data, fallback fonts.

## Tests
`tests/browser/test_stage27b_accessibility.py`: auth borders, all 16 emotions + tag pills, hit areas per screen at 320/390, Edit/Delete separation, focus rings, accessible names, overflow at 320/375/390/430/768/1280. Fails on the pre-27b `index.html` (8 failures), passes after.
