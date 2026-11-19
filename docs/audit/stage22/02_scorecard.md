# C. UI/UX scorecard (1-5, higher is better)

Scores are the auditor's judgement from the captured screens (390x844 primary, other viewports as noted) and the measurements in `measurements.json`. Every score below 4 cites a finding ID from `01_findings_register.md`.

| Screen | Hierarchy | Readability | Navigation | Discoverability | Consistency | Mobile | Accessibility | Emotional | Efficiency | Polish | Avg |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Splash | 5 | 4 | 4 | 4 | 5 | 5 | 3 | 5 | 3 | 4 | 4.2 |
| Auth (Log In / Sign Up / Forgot) | 4 | 4 | 4 | 4 | 4 | 3 | 3 | 4 | 3 | 4 | 3.7 |
| Home | 5 | 4 | 4 | 4 | 4 | 4 | 3 | 5 | 4 | 5 | 4.2 |
| Record a Dream (entry) | 4 | 4 | 4 | 4 | 4 | 3 | 4 | 5 | 3 | 4 | 3.9 |
| Emotion Wheel explorer | 5 | 4 | 4 | 4 | 4 | 3 | 4 | 5 | 4 | 5 | 4.2 |
| Interpreting / error | 5 | 5 | 4 | 4 | 5 | 5 | 4 | 5 | 4 | 5 | 4.6 |
| Dream Detail | 4 | 4 | 3 | 4 | 3 | 4 | 4 | 4 | 4 | 4 | 3.8 |
| Journal | 3 | 4 | 3 | 4 | 3 | 4 | 3 | 4 | 3 | 4 | 3.5 |
| Loom Map / Network | 3 | 3 | 3 | 2 | 3 | 3 | 3 | 4 | 2 | 4 | 3.0 |
| Loom Map / node sheet | 4 | 4 | 3 | 3 | 4 | 4 | 4 | 4 | 3 | 4 | 3.7 |
| Loom Map / Filters sheet | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4.0 |
| Loom Map / Timeline + element detail | 3 | 3 | 3 | 3 | 3 | 4 | 4 | 4 | 3 | 3 | 3.3 |
| Loom Map / List | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4.0 |
| Insights | 4 | 3 | 4 | 3 | 3 | 4 | 3 | 4 | 4 | 4 | 3.6 |
| Settings menu | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4.0 |
| Profile | 3 | 4 | 3 | 3 | 3 | 4 | 4 | 3 | 3 | 3 | 3.3 |
| Account / Data / Delete | 3 | 4 | 3 | 3 | 3 | 4 | 4 | 3 | 3 | 3 | 3.3 |
| Privacy / Support | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4.0 |

## Evidence for every score below 4

- **Splash**: Accessibility 3 (aria-hidden, no skip); Efficiency 3: X-01 fixed 2.2s hold
- **Auth (Log In / Sign Up / Forgot)**: Mobile 3, Efficiency 3: A-01 (320x568 form below fold, default tab Sign Up); Accessibility 3: small eye/forgot targets
- **Home**: Accessibility 3: N-02 (Review in Loom Map link 18px; footer links 24px), 10.9px nav labels N-01
- **Record a Dream (entry)**: Mobile 3, Efficiency 3: R-02 Continue off-screen at keyboard height
- **Emotion Wheel explorer**: Mobile 3: R-01 landscape unusable, R-03 tray at 320x568
- **Dream Detail**: Navigation 3, Consistency 3: D-01 Archive vs Journal
- **Journal**: Hierarchy 3, Navigation 3, Efficiency 3: J-01, Consistency 3: J-03, Accessibility 3: N-02 (32px targets)
- **Loom Map / Network**: L-01 (no visible connections; Discoverability 2, Efficiency 2), L-02 silent 12-node cap, L-04 targets/labels
- **Loom Map / node sheet**: L-01 connected items not interactive (Discoverability 3, Efficiency 3)
- **Loom Map / Timeline + element detail**: L-06 stacked Timeline controls and mid-word cut excerpts
- **Insights**: Readability 3: 11-11.8px captions; Discoverability 3, Consistency 3: I-01, I-02; Accessibility 3: legend toggle 19px (N-02)
- **Profile**: S-01 page nearly empty; naming mismatch with Account
- **Account / Data / Delete**: S-01, S-02 delete flow emphasis

## Reading the scorecard
- Lowest-scoring screens: Loom Map / Network, Loom Map / Timeline detail, Profile, Account, Journal.
- Highest: Interpreting, Emotion Wheel, Home. The recording journey (Stage 19-21) is the strongest part of the product.
- Scores are relative; they are not a user-research result.
