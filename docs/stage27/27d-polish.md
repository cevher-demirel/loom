# Stage 27d — Final visual polish

Only reproducible defects were fixed. No backend, schema, data, navigation, Loom Map or emotion-calculation changes.

## Fixed
**Emotion flower centre label** (Insights "Emotional landscape" and Dream Detail "What it carried"). The dial is drawn in a 300-unit viewBox (r=38) but its label is real text, so at 260/220/176px the dial was only 66/56/45px across and the name/percentage spilled onto the petals.
- Dial radius 38 → 46 (52 for the long name "Anticipation"); the label is now centred over the dial by a flex wrapper instead of hand-tuned pixel offsets, with tighter line-height.
- "Anticipation" uses 12px (the app's text floor) so it fits; other names keep 13–14px.
- The compact 176px wheel (one or two emotions) is used only when the dominant name is ≤5 characters; otherwise the standard 220px wheel, so the dial can hold the name.
- Petal geometry, colours, opacities, angles and all percentages are untouched. Petals shorter than the dial (< ~3% share) are hidden under it, as they already were under the old dial.
- "Layered over time" flower has an empty dial and is unchanged.

## Investigated, not changed
- **Home faint "Loominous" wordmark.** Reproduced only during the splash cross-fade (first ~0.7s: splash opacity 1 → 0 while Home is already painted). Once the splash is `display:none` there is no wordmark element or pseudo-element over Home content at 390 or 1280px (`elementsFromPoint` check, now a test). No change made.
- **Wide screens (≥768px): Home scene crops the moon** (the 400px-high scene uses `slice`), and the brand title sits over the moon. Observed, not a Stage 26 finding I could verify against (the audit files are not in this repo), and fixing it means changing the scene art/height, so it is left for review.

## Not revisited
The Stage 26 audit documents were not available in this session; remaining items were limited to the two named in the brief plus what screenshots at 320–1280px showed. No other reproducible defects were found.

## Tests
`tests/browser/test_stage27d_polish.py`: every Plutchik family as dominant — label text inside the dial (ink box) on the landscape flower at six widths, on the per-dream flower at 320/390/1280 with one and four emotions; 12px floor kept; petals/colours still rendered; no persistent Home wordmark once the splash is gone.
