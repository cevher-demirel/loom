# B. Screen-by-screen audit

Evidence: screenshots in `screenshots/<area>/<name>_<W>x<H>.png` (six viewports: 320x568, 375x667, 390x844, 430x932, 768x1024, 1280x800, plus short/landscape/keyboard-emulated states), `annotated/` for marked-up examples, `measurements.json` for DOM measurements. Finding IDs refer to `01_findings_register.md`.

## 1. Cold start / Splash
Strengths: calm brand moment (moon + wordmark), respects prefers-reduced-motion (0.5s hold). Problems: fixed 1.7s hold + 0.5s fade on every launch (X-01). 

## 2. Auth (Log In / Sign Up / Forgot / Reset)
Strengths: clear tab switch, password reveal eye, plain-language privacy line ("Your own private archive..."), forgot-password flow exists. Problems: at 320x568 the form's password field and button fall below the fold under the illustration; first-time landing is on Sign Up (A-01). Not exercised: real account creation/sign-in (no credentials used; backend mocked).

## 3. Home (Journey A)
Strengths: strongest first impression: moonlit scene, personal welcome, one dominant CTA ("Record a Dream"), "Your recent discovery" card, Journal shortcut. Within a few seconds the purpose (record dreams, find patterns) is clear. Problems: "Review in Loom Map" link 18px tall; footer links (Settings/Privacy/Export) 24px; nav labels 10.9px / 4.41:1 (N-01, N-02). Empty state is warm and instructive ("Your Journal is empty. Record your first dream below...").

## 4. Record a Dream (Journey B)
Strengths: large text box, optional date/place, voice entry, focus ring clear. Problems: Continue below the fold at keyboard height (R-02, emulated). Draft preservation verified by Stage 19/20 tests (not re-tested here).

## 5. Emotion Wheel explorer (Journey B)
Strengths: wheel is simple and inviting; focus vs selection is clear; one dock; tray collapses; Skip clearly labelled. Problems: landscape unusable (R-01); expanded tray cramped at 320x568 (R-03). Colors differ from Insights (I-02).

## 6. Interpreting / error / retry (Journey B)
Strengths: dreamlike, readable at 320-1280; recovery copy is clear ("We couldn't finish interpreting your dream." / "Your words and selected emotions are still here."); Try again is 61px tall; the secondary "Back to my choices" is 36px (minor, covered by N-02). No other issues found. Stage 21 mechanisms untouched.

## 7. Dream Detail
Strengths: good reading hierarchy (date, dream, interpretation, "What it carried", symbols). Problems: back label 'Archive' vs 'Journal' (D-01); emotion flower for 1-2 emotions is decorative rather than informative.

## 8. Journal (Journey C)
Strengths: scannable cards with date and tags; search highlights the match; filter chips; good empty state ("Nothing logged yet...", though the line 'Describe a dream above' points to a control that is the New Dream button). Problems: J-01 (three add paths), J-02 (clipped placeholder), J-03 (unlabelled colour square), J-04 (chips). Search with no results shows an empty state (captured: `06_journal/search_no_results_*`).

## 9. Loom Map: Network / node sheet / Filters / Timeline / List (Journey D)
See `05_loom_map_deep_dive.md`. Summary: attractive and calm, but it shows frequency not connections (L-01), silently caps nodes (L-02), small targets (L-04). Filters sheet is clear (four element types, connection strength, time range, Reset/Apply). List view is the most useful view today (27 elements, counts, tappable rows). Timeline/element detail has stacked Timeline controls and cut excerpts (L-06).

## 10. Insights (Journey E)
See `06_emotional_landscape_review.md`. Strengths: Emotional landscape, recurring themes, dream activity, honest caption ("Percent and 'X of Y' both mean how often a feeling showed up..."), good empty/low-data copy. Problems: I-01, I-02, I-03; caption/legend text 11-11.8px; legend toggle 19px.

## 11. Settings (Journey F)
Strengths: simple four-row menu (Profile, Account, Privacy Notice, Support). Problems: Profile vs Account content split (S-01); delete emphasis (S-02). Export ("Download my dreams (.txt)") is easy to find; password-confirmed delete with "There's no undo." is clear. Not exercised: real export/delete (no production data touched).

## Cross-cutting observations
- Header "Loominous" brand row (172x35) and gear (32px) are small targets on every tab (N-02).
- Dark purple surfaces and gold accents are used consistently; gold is reserved for focus points and counts (good restraint). Glow is strongest in the recording journey and quieter elsewhere (X-02).
- No P0 issues found.
