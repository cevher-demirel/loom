# Stage 24a — entity identity, counts and what "mentioned" means

## Three different measurements (never merged)
| Measure | Source | Where shown | Counts toward Map / relationships? |
|---|---|---|---|
| **Tagged** | the extracted `people / symbols / settings / emotions` of a dream, after alias canonicalisation | Element header ("Found in N dreams"), Dreams tab, Loom Map | yes |
| **Written** (mentioned) | whole-word match of the concept's words in the dreamer's own `raw_text` (never the AI interpretation) | "Also written in M more journal entries without a X tag", and the "Written in these entries, not tagged" list | **no** |
| **Journal search hits** | Journal search box: raw text, interpretation, location, date, tags | Journal list | no |

Why Journal said 6 and the Map said 2 (Dad/Father): the Journal search also reads the AI interpretation and
matches any whole word, while the Map only counts dreams where extraction tagged Father. For the owner's data one
"I saw my dad…" dream carried only an emotion tag, so it was never a Father dream as far as the Map is concerned.
A text mention is **not** promoted to a tag (no silent reprocessing); it is shown separately and openable.

## Alias rules (deterministic, closed lists)
* People (existing, Stage 11/12): brother; sister; mom/mother/mommy; dad/father/daddy; girlfriend/boyfriend/friend. Brother ≠ Father.
* Phrases (new, `CONCEPT_PHRASE_ALIASES` in `index.html` and `main.py`, kept in sync), for symbols and places:
  * `barber shop | barbershop | barber-shop` → **barber shop**
  * `haircut | hair cut | hair-cut | hair cutting | haircutting` → **haircut**
* Canonical slugs are the pre-existing spellings, so no existing key (cache row, personal meaning, chat thread) changes.
  Rows stored under a now-merged *variant* spelling (e.g. an element cached as "barbershop") are untouched and simply
  not looked up again; nothing is deleted. Display labels use the canonical form; the dream text is never rewritten.
* Deliberately NOT merged: Barber chair ≠ Barber shop; haircut ≠ barber shop; "father figure", "brother-in-law",
  "mother nature"; any two generic places that merely look similar. Emotion families and tertiary IDs are untouched.

## Counting
Distinct dream IDs only (`collectDreamElements` keeps one entry per canonical element per dream), so a dream
containing Dad + Father + Daddy counts once.

## Data / migration status
No schema change, no migration, no backfill. Historical dreams are not reprocessed.
