# Loom's eval harness

Answers one question: "did that prompt change actually make interpretations
better, or does it just feel like it did?"

## Running it

```
python3 evals/run_eval.py
```

Needs the same `.env` the app itself needs (`ANTHROPIC_API_KEY`,
`VOYAGE_API_KEY`). Runs all 15 fixtures through the real
`extract_dream_data` + `interpret_dream` pipeline, so it takes a minute or
two and costs a small amount of real API usage -- that's intentional, a
mocked/fake eval wouldn't tell you anything about actual output quality.

## What it checks

Two layers, run on every fixture:

1. **`rubric.py`** -- free, instant, regex-based checks for the things
   that are mechanically checkable: no stock "Across cultures" opener, has
   the 3-5 bullet symbol breakdown, ends with a reflective question, ends
   cleanly (not cut off mid-sentence -- this is what the token-budget and
   non-English-truncation bugs looked like), no explicit religious
   language, no literal future-prediction phrasing, reasonable length.

2. **`judge.py`** -- an LLM-as-judge call. Regex can't tell you whether a
   reading is actually *specific* to this dream versus generic enough to
   paste onto any dream, so a second Claude call reads the dream and the
   interpretation side by side and scores it 1-5, plus flags on tone and
   whether it ends cleanly.

## Reading the output

A table prints to the terminal (pass counts + judge score per fixture),
plus a full JSON report gets saved to `evals/results/run_<timestamp>.json`
(gitignored -- these are local run outputs, not source) with every actual
interpretation text, in case a low score needs digging into.

## Workflow

Before changing `INTERPRETER_SYSTEM_PROMPT` or the extraction prompt in
`engine.py`, run this once and note the average score and pass rate. Make
the change. Run it again. Compare. That comparison is the actual evidence
for whether the change helped -- not a single example eyeballed by hand.

## Adding fixtures

`fixtures.py` is meant to stay stable once a case is in it -- add new
fixtures when a new kind of dream reveals a new failure mode (that's how
the existing 15 got picked: short/long, non-English, vague, emotionally
intense, religious imagery, near-duplicate symbols, prediction-bait,
mundane, positive). Don't edit existing fixtures' text, or comparisons
across runs over time stop meaning anything.
