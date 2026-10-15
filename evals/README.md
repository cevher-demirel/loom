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

## Phase 6 -- automated prompt search (`dspy_optimize.py`)

The harness above still requires a person to hand-edit
`INTERPRETER_SYSTEM_PROMPT`, run the eval, and judge whether it helped.
`dspy_optimize.py` automates the "try a different wording" half of that
loop: it hands `rubric.py` + `judge.py` to [DSPy](https://dspy.ai) as a
scoring function, and DSPy searches over candidate instructions (via
MIPROv2), scoring each one against a held-out validation split of the
fixture set so a candidate can't just overfit to the examples it was
tuned on.

```
pip install -r requirements-dspy.txt
python3 evals/dspy_optimize.py
```

Needs `optuna` (in `requirements-dspy.txt`) for MIPROv2's trial search,
and the same `.env` as everything else here. Costs noticeably more than
`run_eval.py` -- it's scoring several candidate prompts, not just the one
currently live -- so `NUM_TRIALS` at the top of the file is a dial, not a
constant.

**What a run actually produces:** a held-out-validation score for the
current production prompt, a held-out-validation score for whatever DSPy
's search landed on, and the candidate instructions themselves, saved to
`evals/results/dspy_optimized_prompt.txt` (gitignored, like every other
eval result). The candidate is never written back into `engine.py`
automatically -- a person reads it, runs it through `run_eval.py`'s fuller
check (or a few real dreams) and decides, the same judgment call Phase 1
exists to support, just with DSPy supplying candidates instead of a
person's own rewording.

**The first real run's result, for what it's worth:** DSPy's search
converged back to the *existing* hand-written prompt, word for word --
of the 4 candidates it generated, the original one it was seeded with
still scored highest. The ~2-point score gap reported (0.809 vs 0.829) is
LLM-judge run-to-run noise, not a real difference, since the instructions
were literally identical text. That's a legitimate finding in itself:
evidence that `INTERPRETER_SYSTEM_PROMPT` is already a strong local
optimum for this metric, at least within what a light MIPROv2 search
explored -- not a failed experiment.
