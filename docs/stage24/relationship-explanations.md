# Stage 24c — Similar Dreams reasons and Recurring connections

## Similar Dreams
* Source of the list is unchanged: `/dreams/{id}/similar` (stored embeddings, no AI call, nothing re-embedded per render).
* The chip used to read "76% match". That number is `cosine(embedding_a, embedding_b) × 100`, a ranking signal between
  two meaning vectors, **not** a probability or a measure of shared facts. The chip now says **"Similar meaning"**
  (tooltip explains it). `match` is still returned by the API, unchanged.
* Reasons under each card are computed in the browser from stored data only:
  * *Same person / setting / symbol / emotion: …* — canonical elements tagged on both dreams (alias-aware).
  * *Both entries mention: …* — a closed list of phrases (barber shop, haircut) and the four family words appear as whole
    words in both dreams' own text but are not already a shared tag. Labelled "mention", never "same".
  * With no supported reason the card says "Similar overall meaning. No shared tags." — nothing is invented.
* Each card has a real **Open this dream** button. From a dream, Back returns to the previous dream.

## Recurring connections (Dream Detail, between "What it carried" and Similar dreams)
Only when something is supported: elements of this dream that occur in ≥ 2 dreams ("Brother — appears in 12 dreams",
max 4) and pairs of this dream's elements sharing ≥ 2 dreams ("Brother + Barber shop — together in 2 dreams", max 3).
Element rows open the element screen (Back returns to the dream); pair rows open the Map connection preview.
No stored interpretation is rewritten and no similarity is presented as a shared psychological meaning.
