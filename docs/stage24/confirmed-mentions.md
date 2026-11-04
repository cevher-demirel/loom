# Stage 24f — the October 31 dream and confirmed person relationships

## What was inspected (and what could not be)
Production data was **not** queried (CLAUDE.md forbids live/production access), so the stored row of the owner's
October 31 dream was not read directly. The conclusion below rests on the owner's screenshots plus a full trace of the code
path, and is reproduced with synthetic data mirroring both dreams.

## Root cause
1. **Extraction missed the tag.** The Oct 31 card shows *trust* and *Haircut* only; its `people` list has no Brother
   (the Nov 3 dream, tagged Brother, appears under Brother → Dreams; Oct 31 does not).
2. **Brother → Dreams is a client-side filter** of the loaded archive: `symbolScreenOccurrences` keeps dreams whose
   `collectDreamElements` contains `person:brother`. That list has no pagination or hidden filter: nothing excludes a
   dream that actually carries the tag. "Found in 12 dreams" = tagged dreams only, not a broader total.
3. Identity normalisation is not the cause: "my brother", "brother", "the brother" all map to `person:brother`.
   The dream simply has no person tag, so it never enters the concept.
4. The extraction model decides tags per dream; the owner text clearly says "my brother", so the correct fix is to let the
   dreamer confirm it, not to guess for them.

## Behaviour
* Dreams whose own text uses the concept's words (whole word, raw text only) but that are not tagged are listed on the
  element screen under **"Written in these entries, not tagged"** — never counted as tagged.
* Each such row has **"Yes, this is Brother"**. Confirming stores a row in the new `entity_confirmations` table
  (additive `CREATE TABLE IF NOT EXISTS`; user-scoped; person category only; idempotent; reversible with **Remove**).
* The server overlays confirmed people onto each dream's `people` (`with_confirmations`) for the archive list and for AI
  grounding, and marks them in `confirmed_people`. Therefore Journal People filter, Dream Detail, Loom Map counts,
  related dreams, relationship counts and element reflections all agree. The stored dream, its interpretation and its
  extraction columns are never modified; the row is removed with its dream and with the account.
* Three kinds of link stay distinct: **tagged** (extracted), **Added by you** (confirmed), **written, not tagged**
  (unconfirmed text mention). Semantic similarity is separate (24c) and never becomes a confirmation.
* Navigation: opening a dream from the element screen returns to that element's Dreams tab; Back again returns to the Map.

## Migration status
One new table, created lazily. No backfill, no historical reprocessing. Rollback = drop `entity_confirmations`
(only user-confirmed rows live there).
