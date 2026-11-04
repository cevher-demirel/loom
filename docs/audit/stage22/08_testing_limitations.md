# I. What was tested, and what was not

## Tested (actually run)
- Baseline: `git` main at 4117f82 (merge of Stage 21 PR #34, CI green); local `pytest tests -q`: **462 passed** in 4m58s (includes the Chromium browser tests).
- Screenshots: Chromium (Playwright) driving the real `index.html` from file:// with a **mocked backend** and deterministic seeded dreams (`seed.py`: 0, 3, 5, 10, 30, 120 dreams, single and multi-emotion, legacy-style rows with no emotions_reported).
- Viewports: 320x568, 375x667, 390x844, 430x932, 768x1024, 1280x800; extras 390x600 (short), 844x390 (landscape), 390x420 (keyboard-height emulation).
- Measurements (`measurements.json`) at 320x568, 390x844, 1280x800 on Home, Record, Wheel, Wheel-selected, Journal, Loom Map, Insights, Profile: tap-target sizes, text under 12px, unnamed controls (0 found), horizontal overflow (none found), computed contrast.
- Static CSS/JS analysis of index.html (tokens, duplicate selectors, z-index, radii, durations, focus rules, reduced-motion blocks: 13, `:focus-visible` rules: 32).

## Not tested / limits
- **Real keyboard:** a mobile OS keyboard cannot be opened in this environment. The keyboard-open state is an emulated viewport resize (390x420); true overlap behaviour with iOS/Android keyboards is unverified.
- **Safari / iOS / Firefox / real phones:** only Chromium. No Safari claim is made. Safe-area insets, 100vh behaviour and font rendering on iOS are unverified.
- **Production and authentication:** no live site, no real account, no production credentials, no real AI output. Sign-up/sign-in, export and account deletion were viewed as UI only. AI-dependent parts (Interpretation text, Ask-about-this-dream, symbol reflections, Insights reflection) were not rendered with real content; where the mock returned an error (element detail reflection) the screenshot shows the failure state and is labelled as induced.
- **Voice recording:** the control is visible; microphone behaviour not exercised.
- **Screen readers:** no VoiceOver/TalkBack run. Accessible names were checked programmatically only (all visible controls had names).
- **Contrast:** computed from CSS colours and approximated backgrounds; text on gradients or SVG fills (wordmark, wheel labels, gradient buttons) reports false lows and was reviewed visually instead. The only confirmed sub-AA text is the 10.9px bottom-nav labels at 4.41:1.
- **Performance:** not measured.
- Scores are expert judgement, not user research.
- Capture notes: the app shows a ~2.2s splash on every cold load; captures wait for it to hide.
