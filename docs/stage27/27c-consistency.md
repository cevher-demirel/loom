# Stage 27c — UI consistency

Text and CSS only. No backend, schema, data, navigation or Loom Map graph changes. Source: Stage 26 findings F-11 and related small-label items.

## Changes
| Area | Change |
|---|---|
| Typography | Every `font-size` of 0.70–0.74rem (11.2–11.8px) is now 0.75rem (12px): "Your dream", "swipe →", tags, small captions, legends. Fraunces/Work Sans, headings and hierarchy untouched. |
| Punctuation | 28 visible ` -- ` in HTML copy and JS strings are now ` — ` (em dash). Comments, code and data values untouched. |
| Labels | Sentence case for small UI labels: Reset filters, Clear all, View list, Use photo, About you. "Show fewer" → "Show less" (matches the other Show more/Show less toggles). Auth actions (Log In, Sign Up, Create Account) unchanged. |
| Chip rows | **No change.** Tested at 320–1280px: when the Journal filter row scrolls (≤ ~440px wide), the last chip is visibly cut off; at 768px+ all chips fit. A test now locks this in. |

## Tests
`tests/browser/test_stage27c_consistency.py` (33): 12px floor and no `--` in rendered text across 6 screens × 3 widths, source scan for `--` in copy, label wording, chip-row cue at 320/375/390/430/768/1280, View list hit area + name + focus ring, no horizontal overflow at all six widths.

## Limitations
- Around 437–441px viewport width only a ~1–6px sliver of the last chip is cut off, a weak scroll cue. Not changed (no arrows/gradients per brief).
- Other horizontally scrolling card rows (symbol cards, similar dreams) were not changed.
- Chromium only; synthetic data; fallback fonts.
