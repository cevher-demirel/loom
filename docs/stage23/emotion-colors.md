# Stage 23f - emotion colour and naming reference

Single source of truth: `EMOTION_TAXONOMY[].color` (the Emotion Wheel).

| Canonical (stored) | Wheel / user-facing | Colour |
|---|---|---|
| Joy (`happy`) | Happy | #e0b81a |
| Trust | Trust | #4e7a46 |
| Fear | Fear | #3d9be0 |
| Surprise | Surprise | #1ebcf5 |
| Sadness (`sad`) | Sad | #7266b5 |
| Disgust | Disgust | #c02cbc |
| Anger (`angry`) | Angry | #f0361a |
| Anticipation | Anticipation | #d96b26 |

Blended Plutchik emotions keep a distinct colour: the RGB midpoint of their two
parents (Love = Joy+Trust, Submission = Trust+Fear, Awe = Fear+Surprise,
Disapproval = Surprise+Sadness, Remorse = Sadness+Disgust, Contempt =
Disgust+Anger, Aggressiveness = Anger+Anticipation, Optimism = Anticipation+Joy).

Legend/label text is lightened toward white only as far as needed for 4.6:1
contrast on the app background. Petals/dots use the saturated colour.

Names: only the display changes (Joy->Happy, Sadness->Sad, Anger->Angry).
Stored values, canonical ids and the taxonomy are untouched.

Journal emotion pills: colour = the pill's own emotion if it is a known emotion,
otherwise the dream's leading family (dreamer-selected family first, AI reading
as fallback). The pill text is never changed.

Small samples: with fewer than 5 eligible dreams the Landscape adds "An early
reading from N dreams. Your patterns will become clearer over time."
