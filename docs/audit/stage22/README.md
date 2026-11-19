# Stage 22 - UI/UX audit review package (audit only)

Baseline: `main` @ `4117f82` (Stage 21 / PR #34 merged, CI green). Local suite: 462 passed. **No application source, backend, schema, taxonomy or user data was changed**; this branch adds documentation, screenshots and audit scripts only.

| File | Deliverable |
|---|---|
| this README | A. Executive summary |
| `03_screen_by_screen.md` | B. Screen-by-screen audit |
| `01_findings_register.md`, `findings.csv` | Every finding: screen, element, problem, viewport, why, fix, complexity, regression risk, priority |
| `02_scorecard.md`, `scorecard.csv` | C. UI/UX scorecard (18 screens x 10 criteria) with evidence for scores < 4 |
| `annotated/` | D. Annotated screenshots (9) |
| `04_design_system_proposal.md` | E. Design-system proposal |
| `05_loom_map_deep_dive.md` | F. Loom Map deep dive |
| `06_emotional_landscape_review.md` | G. Emotional Landscape review |
| `07_stage23_roadmap.md` | H. Stage 23 roadmap (8 batches) |
| `08_testing_limitations.md` | I. Testing limitations |
| `screenshots/`, `09_screenshot_index.md` | 324 screenshots, 6 viewports + short/landscape/keyboard-emulated |
| `measurements.json`, `tools/` | Raw DOM measurements and the seed/capture/measure scripts used |

## A. Executive summary - five most important findings
1. **The Loom Map shows frequency, not connections (L-01).** Element-to-element lines were removed, node-sheet "Connected to" items are not tappable, and the connection sheet is unreachable. The signature feature does not yet deliver "discover connections".
2. **The map silently hides data (L-02).** The Network caps at 12 nodes; with 27 elements, 15 are missing and the note that should say so is never filled in. Trust matters.
3. **Core journey breaks in two situations (R-01, R-02).** Rotated phone (844x390): the Emotion Wheel is not visible. Keyboard-height viewport (390x420, emulated): Continue is below the fold.
4. **Touch and text sizes are below standard in many places (N-01, N-02).** Two links are under the WCAG 2.2 AA 24px minimum (18px, 19px); many controls are 28-36px (gear, back, chips, view toggle, zoom); rendered text under 12px on every tab; bottom-nav labels are 10.9px at 4.41:1.
5. **The same thing is called, and coloured, differently (D-01, S-01, I-02).** "Archive" vs "Journal"; "Profile" vs "Account" content split; wheel and Landscape colours differ for the same emotion family.

No P0 found. 5 P1, 17 P2, 1 data-integrity question for the owner (Landscape ignores the user's own picks when AI tags exist - not changed).

## Recommendation
**Change first:** batch 1-3 (recording-journey robustness in landscape/keyboard, touch targets and small text, Loom Map honesty note), then the Loom Map connection reveal (batch 4).
**Deliberately leave alone:** the visual identity (palette, lotus, moon, wheel, flower), the Home screen, the interpreting/error screens, the Stage 19-21 recording flow and submission mechanism, the Filters sheet and List view, the emotion taxonomy, and all calculations.

## Owner approval needed
Stage 23 start; the Landscape basis decision (I-03); whether Loom Map connection lines should return in any form (L-01 reverses an earlier "Option 2" decision); any change to emotion colours (I-02); merging this docs-only PR.
