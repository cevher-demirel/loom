# G. Emotional Landscape review

Evidence: `screenshots/08_insights/` (populated 30 and 3 dreams, empty), `annotated/A6`, code read of `computeEmotionFrequency`, `emotionPetalSize`, `EMOTION_COLORS`.

## How it works (read, not changed)
- Per dream, tags = `emotions_plutchik` if present, otherwise `emotions_reported`. Each recognised tag counts once per dream. Denominator = dreams with at least one recognised tag. `pct = round(count/denominator*100)`.
- Petal length/width scale with sqrt(pct); opacity 0.35 + pct*0.0055; 16 emotion names (8 families + 8 blends) are plotted.
- Centre label shows the dominant emotion, its %, and "X of Y". Legend defaults to the five most frequent; "Show all emotions" expands. A caption explains that percentages can total more than 100%.

## Findings
- **Clear:** the caption "Percent and 'X of Y' both mean how often a feeling showed up, not how strongly" is honest and well worded. Empty state ("Your emotional landscape will appear when a dream has an emotional reading") is understandable.
- **Petal size meaning (I-01-adjacent):** users can see the biggest petal; they cannot read sizes (sqrt scaling is not linear and no scale is shown). Acceptable as an impression, but only the dominant emotion shows a number inside the flower.
- **Colour consistency (I-02):** the same family has different colours on the Emotion Wheel and in the Landscape (Fear blue vs violet, Sadness lavender vs blue, Trust dark green vs mint, Disgust magenta vs purple), and "Happy" on the wheel is "Joy" here. Within the Landscape/Dream Detail the mapping is consistent.
- **Legend readability:** legend entries use lightened text colours for dark hues (good); caption and legend text measure 11-11.8px.
- **Zero/low data (I-01):** zero state is fine. With 3 dreams the headline reads "67% - 2 of 3", which looks authoritative; no "early reading" note exists. Recurring themes use a similar "once a few dreams have been read" message, which is a good pattern to reuse.
- **Misleading risk:** moderate for very small samples; low otherwise. The flower is attractive and not distorting beyond the sqrt scaling.

## Data-integrity finding (I-03) - documented, NOT changed
Since Stage 19 users select emotions explicitly (`emotions_reported`), but the Landscape prefers the AI's `emotions_plutchik` and only falls back to the user's picks when the AI tags are absent. Specific labels like "Worried" are not in the 16 plottable names, so they cannot contribute at all. The owner should decide whether the Landscape is meant to show "what the AI read" or "what you felt", and then say so in the caption. No denominator or counting rule was altered.

## Recommendations (copy/visual only)
1. One emotion-colour source of truth shared by wheel, Landscape and Journal (Stage 23 batch 5).
2. "Early reading from N dreams" note under the flower when dreams-with-reading < 5.
3. State the basis in the caption once the owner decides (I-03).
