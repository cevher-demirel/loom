"""
evals/dspy_optimize.py -- Phase 6 of Loom's engineering roadmap: DSPy-style
prompt optimization.

Phases 1-5 built the pieces this depends on: evals/rubric.py + judge.py are
a scoring function (a "metric," in DSPy's vocabulary), and evals/fixtures.py
is a fixed dataset. DSPy needs exactly those two things to do its job --
search over candidate instructions (and, in heavier modes, few-shot
examples) for a prompt, scoring each candidate against the metric, instead
of a person hand-editing INTERPRETER_SYSTEM_PROMPT and re-running the eval
harness by feel.

This is a dev-time, offline tool, not something the running app depends on
-- dspy lives in requirements-dspy.txt, never requirements.txt, the same
split already used for pytest/httpx in requirements-dev.txt. What comes out
of a run is a candidate replacement for INTERPRETER_SYSTEM_PROMPT in
engine.py, printed for a person to read and decide whether to adopt --
never written back into engine.py automatically. A prompt that scores
higher against this specific metric on this specific 15-fixture set isn't
automatically a better prompt; the same judgment call Phase 1 exists to
support (run the eval, look at the actual outputs, decide) still applies
here, just with a wider, automated search feeding it candidates instead of
a person's own rewording.

Usage (same .env as the rest of the app -- ANTHROPIC_API_KEY, VOYAGE_API_KEY):

    pip install -r requirements-dspy.txt
    python3 evals/dspy_optimize.py

Costs real API usage -- more than evals/run_eval.py's single pass, since
optimization means scoring many candidate instructions, each against a
held-out validation split, not just the current prompt once. See
`TRAIN_SIZE`/`NUM_TRIALS` below to scale that up or down.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dspy  # noqa: E402

import engine  # noqa: E402  (path insert above has to come first)
from fixtures import FIXTURES  # noqa: E402
from rubric import run_checks  # noqa: E402
from judge import judge_interpretation  # noqa: E402

# Every third fixture (by position in the stable, hand-picked list in
# fixtures.py) goes to the held-out validation split, so it spreads across
# categories rather than e.g. grabbing only the last few. Optimization only
# ever sees TRAIN; scoring the result happens on VAL, which it never
# searched against -- the same reason a model's test set stays separate
# from its training set. Skipping this and optimizing-and-measuring on the
# same fixtures would just be curve-fitting a prompt to 15 specific
# examples, not evidence it generalizes.
VAL_EVERY_NTH = 3
NUM_TRIALS = 6  # kept small on purpose -- see the module docstring on cost


def _build_dataset():
    """
    Turn fixtures.py into DSPy Examples. extract_dream_data runs once per
    fixture here (a real API call) so both the baseline and every
    optimization trial interpret the *same* extracted data -- isolating
    what's actually being optimized (the interpretation step) from the
    extraction step, which Phase 6 isn't touching.
    """
    examples = []
    for fx in FIXTURES:
        print(f"  extracting: {fx['id']} ...", flush=True)
        extracted = engine.extract_dream_data(fx["text"])
        ex = dspy.Example(
            dream_text=fx["text"],
            extracted=json.dumps(extracted),
            lang=fx["lang"],
        ).with_inputs("dream_text", "extracted")
        examples.append(ex)

    train = [ex for i, ex in enumerate(examples) if i % VAL_EVERY_NTH != 0]
    val = [ex for i, ex in enumerate(examples) if i % VAL_EVERY_NTH == 0]
    return train, val


class InterpretDream(dspy.Signature):
    __doc__ = engine.INTERPRETER_SYSTEM_PROMPT  # the exact prompt running in production today, as DSPy's starting point to improve on

    dream_text: str = dspy.InputField(desc="The dream exactly as the person described it.")
    extracted: str = dspy.InputField(desc="JSON: symbols, emotions, people, settings, and themes already extracted from the dream.")
    interpretation: str = dspy.OutputField(desc="A grounded, specific interpretation of this dream, ending in a reflective question.")


def loom_metric(example, pred, trace=None):
    """
    The score DSPy optimizes against -- literally the same two tools the
    eval harness already uses (rubric.py's mechanical checks, judge.py's
    LLM-as-judge score), combined into one float in [0, 1] so DSPy has a
    single number to climb. Never a new, separate notion of "good" invented
    just for this script -- if it were, a prompt could score well here and
    still fail the actual eval harness, which would defeat the point.
    """
    interpretation = getattr(pred, "interpretation", "") or ""
    checks = run_checks(interpretation, example.dream_text, lang=example.lang)
    applicable = [v for v in checks.values() if v is not None]
    check_fraction = (sum(1 for v in applicable if v) / len(applicable)) if applicable else 0.0

    judged = judge_interpretation(example.dream_text, interpretation)
    judge_fraction = (judged.get("score") or 0) / 5

    return 0.5 * check_fraction + 0.5 * judge_fraction


def _average_score(module, examples):
    scores = [loom_metric(ex, module(dream_text=ex.dream_text, extracted=ex.extracted)) for ex in examples]
    return sum(scores) / len(scores) if scores else 0.0


def run():
    lm = dspy.LM(model="anthropic/claude-sonnet-5-5", max_tokens=1200)
    dspy.configure(lm=lm)

    print("Building dataset from evals/fixtures.py (one extract_dream_data call per fixture)...")
    train, val = _build_dataset()
    print(f"Split: {len(train)} train, {len(val)} held-out validation\n")

    baseline = dspy.Predict(InterpretDream)

    print("Scoring the CURRENT production prompt on the validation split...")
    baseline_score = _average_score(baseline, val)
    print(f"Baseline (current INTERPRETER_SYSTEM_PROMPT) avg score on val: {baseline_score:.3f}\n")

    print(f"Running MIPROv2 (light, {NUM_TRIALS} trials, instructions-only -- "
          f"no few-shot demos, see max_bootstrapped_demos/max_labeled_demos below)...")
    optimizer = dspy.MIPROv2(
        metric=loom_metric,
        auto=None,                 # explicit num_candidates/num_trials below instead --
        num_candidates=4,          # "light" bundles its own trial count, which collides
        max_bootstrapped_demos=0,  # with setting num_trials ourselves. instruction search
        max_labeled_demos=0,       # only, not few-shot examples -- keeps the result a
        num_threads=1,             # prompt a person can actually read and adopt, not a
        verbose=False,             # context window full of transcripts
    )
    compiled = optimizer.compile(
        student=dspy.Predict(InterpretDream),
        trainset=train,
        num_trials=NUM_TRIALS,
        minibatch=False,  # our val/train sets are tiny -- full eval each trial, not a sampled slice
    )

    print("\nScoring the OPTIMIZED prompt on the same held-out validation split...")
    optimized_score = _average_score(compiled, val)

    optimized_instructions = compiled.signature.instructions

    print("\n" + "=" * 90)
    print(f"Baseline avg score (current prompt):   {baseline_score:.3f}")
    print(f"Optimized avg score (DSPy candidate):  {optimized_score:.3f}")
    print("=" * 90)

    if optimized_score > baseline_score:
        print(
            "\nDSPy found a candidate that scored higher on the held-out split. "
            "This is evidence worth looking at, not an instruction to copy-paste "
            "blindly -- read it, sanity-check it against a few real dreams (same "
            "workflow as evals/run_eval.py), and decide whether it's actually "
            "better or just better-fit to these 15 fixtures specifically."
        )
    else:
        print(
            "\nThe current hand-written prompt held its own against the search --"
            " a legitimate result, not a failure. It means INTERPRETER_SYSTEM_PROMPT"
            " is already a strong local optimum for this metric, at least within"
            " what MIPROv2 explored in this run."
        )

    print("\nCandidate instructions DSPy arrived at:\n" + "-" * 90)
    print(optimized_instructions)
    print("-" * 90)

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "dspy_optimized_prompt.txt")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(
            f"baseline_avg_score: {baseline_score:.3f}\n"
            f"optimized_avg_score: {optimized_score:.3f}\n\n"
            f"{optimized_instructions}\n"
        )
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    run()
