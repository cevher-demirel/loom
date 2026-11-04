# H. Stage 23 roadmap (proposal only - needs owner approval)

Small, separately reviewable PRs, ordered by value to the core journey and the Loom Map. All are front-end only (`index.html`, tests, screenshots); none touches backend, persistence, the emotion taxonomy, the AI prompts, or the Stage 21 submission mechanism.

| # | Batch | Screens | Exact changes | Benefit | Complexity | Regression risk |
|---|---|---|---|---|---|---|
| 1 | Recording journey robustness | Record, Wheel explorer | R-02 sticky Continue above keyboard (visualViewport) and collapse date/voice rows on focus; R-01 landscape/short layout (hide bottom nav, wheel + groups side by side at <=420px height); R-03 tray title/path at <=340px | Core journey works rotated and with keyboard | M | Medium |
| 2 | Touch targets and small text | All tabs | N-02: 44px hit-areas for gear, back, search, chips, zoom, view toggle, Home links, legend toggle; N-01: nav labels 12px and lighter muted token; min 12px rendered text | Accessibility with no visual redesign | S | Low |
| 3 | Loom Map honesty | Loom Map Network | L-02 fill dropped-note ("Showing 12 of N"); L-03 low-data caption; L-04 label min size | Trust | S | Low |
| 4 | Loom Map connections | Loom Map Network + node sheet | L-01: selected node draws faint lines to co-occurring nodes; "Connected to" items become buttons opening the existing connection sheet; L-05 use spare height | Signature feature finally shows connections | M | Medium |
| 5 | Naming and copy | Journal, Dream Detail, Settings, Timeline | D-01 'Archive'->'Journal'; S-01 move About You to Profile; L-06 rename inner Timeline tabs, clamp excerpts; J-02 placeholder; J-01 drop header + | Orientation and consistency | S-M | Low-Medium |
| 6 | Colour and emotion consistency | Wheel, Landscape, Journal | I-02 single emotion-colour table; Happy/Joy label; J-03 aria-label for swatch; I-01 low-sample note; (I-03 after owner decision) | One colour = one family | M | Medium |
| 7 | Design tokens (additive) | Global | Define radius/space/type/motion/z tokens; migrate one component family per sub-PR; resolve duplicate selector blocks (#interp-wait, header.top, #home-record-btn...) | Cohesion, fewer overrides | M-L | Medium |
| 8 | Polish | Splash, Auth, Delete | X-01 splash hides when ready (min 600ms); A-01 remember last tab, compact illustration on short screens; S-02 danger-button delete section; X-02 document primary-button rule | Faster, calmer start | S | Low |

## Required for every batch
- **Tests:** existing 462 tests stay green; add Playwright assertions for the changed targets (size >=44, no horizontal overflow) at 320x568, 375x667, 390x844, 430x932, 768x1024, 1280x800; landscape 844x390 for batch 1.
- **Screenshot comparison:** before/after pairs from `docs/audit/stage22/screenshots` at the same viewports and seeded data (`seed.py`), attached to the PR; no unintended diffs on untouched screens.
- **Files:** `index.html`, `tests/browser/*`, docs/screenshots. Nothing else.
- Real-device checks (iOS Safari keyboard, safe areas) before merging batch 1 and 2.
