# Stage 23f-2 - Emotional Landscape: dreamer's selection leads

## What is stored (inspected, nothing mutated)
- `emotions_plutchik`: the AI reading, restricted to the fixed 16-word Plutchik list.
- `emotions_reported`: written by the wheel (`feelBuildEmotionsReported`): first the
  Plutchik PRIMARY word of each chosen family (`EMOTION_TAXONOMY[].plutchik`,
  capitalised: Joy, Trust, Fear, Surprise, Sadness, Disgust, Anger, Anticipation),
  then the chosen specific (middle/leaf) labels. Pre-wheel records tagged mood from the
  same eight-word set (see the `emotions_plutchik` comment in main.py).

## Mapping (no guessing)
Of 118 distinct taxonomy labels, 117 belong to exactly one family; "Delighted" appears
under Happy and Surprise. Three specific labels share a name with a blended Plutchik
emotion: Awe, Contempt, Disapproval. Because every wheel selection already carries its
family's primary word, the Landscape reads **only the eight exact primary words** from
`emotions_reported`. Specific labels and blended names found there are ignored.

## Calculation
Per dream: if `emotions_reported` contains >=1 primary -> those primaries (once each).
Else -> `emotions_plutchik` (unchanged). Else -> the legacy `emotions_reported`
fallback (unchanged). Denominator and "count once per dream" are unchanged.
Stored records are never modified.

## Effect
Dreams where the dreamer picked a family: the Landscape now shows their family instead of
the AI's. Counts for those dreams can differ from before; dreams without a selection are
unchanged. The caption states how many dreams use the dreamer's own selection.
Dream Detail's per-dream "What it carried" wheel is unchanged in this batch.
