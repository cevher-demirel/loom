# E. Design-system proposal (not implemented)

## What exists today (measured from index.html at 4117f82)
- Tokens: 8 colour tokens + 2 font tokens + glow/sheen/button gradient tokens in one `:root` block. 495 `var(--...)` uses vs 82 raw hex colours (many inside SVG art).
- No tokens for spacing, radius, type scale, z-index, motion or tap size.
- Radii: 17 distinct values (2, 3, 4, 7, 8, 9, 10, 11, 12, 14, 16, 17, 18, 20, 22px, 50%, 999px).
- Font sizes: 36 distinct declarations; 7 below 12px (0.66-0.74rem, 9.5px). Measured rendered text under 12px on every tab (6 on Home, 59 on Journal at 390).
- z-index: 15 distinct values from -3 to 999.
- Transitions: 10 distinct durations (0.15-0.5s).
- Selectors re-declared 3+ times: 22 (e.g. `#interp-wait` x4, `#app-shell header.top` x5, `#home-record-btn` x3, `.loom-graph-node` x3, `#feel-go-btn` x3) - later rules silently override earlier ones, mostly from stage-by-stage patching.
- Two primary-button looks (glow gradient vs flat lavender) used without a stated rule.
- Emotion colours defined in three places with different values (wheel taxonomy colours, `EMOTION_COLORS`, `EMOTION_LEGEND_TEXT`).

## Proposed compact token set
```
Colour   --bg #0a0a1a  --surface #15132f  --surface-2 #1d1a44  --border #332f66
         --accent #8f8aef (links/focus)  --gold #f2c14e (focal points only)  --danger #e5676b
         --text #ece9fb  --text-muted #a9a1d4 (raise from #9b93c9 for small text)
Type     display Fraunces; body Work Sans
         scale: 12 / 14 / 16 / 20 / 26 / 32 px (minimum 12px for any rendered text)
Space    4 / 8 / 12 / 16 / 24 / 32
Radius   8 (inputs, chips) / 14 (cards) / 22 (sheets, primary buttons) / 999 (pills)
Tap      --tap 44px minimum hit-area
Motion   --fast .15s  --base .25s  --slow .5s (ease-out); all disabled under reduced motion
Z        base 0, sticky 10, nav 40, sheet 50, modal 60, toast 70
Emotion  one table: family -> colour -> label (Happy/Joy resolved once), used by wheel, landscape, journal swatch
```
## Component rules
- **Primary button:** glow gradient only in the recording journey (Record a Dream, Add to Dream, Try again); flat accent elsewhere. Heights 44/48.
- **Secondary / link buttons:** 44px hit-area even when visually small.
- **Chips:** 32px visual, 44px hit-area (pseudo-element).
- **Sheets/dialogs:** one radius, one backdrop, one close affordance; destructive confirmations use the danger button.
- **Icons:** one stroke width (2px, round caps) - already consistent.
- **Glow:** reserved for primary focal point per screen; no glow on secondary controls.
- **Empty states:** one pattern (dashed card, title, one sentence, one action) - already close.

## Rollout advice
Introduce tokens additively (define, then migrate one component family per PR) so no screen changes appearance until its batch lands. Do not refactor CSS wholesale.
