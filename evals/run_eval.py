"""
evals/run_eval.py -- runs the fixture set through engine.py's real
extraction + interpretation pipeline and reports quality.

Usage (from the project root, with your .env in place -- same
ANTHROPIC_API_KEY and VOYAGE_API_KEY the app itself needs):

    python3 evals/run_eval.py

This calls the real Claude and Voyage APIs once per fixture (extraction +
interpretation + judging), so a full run of the default 15 fixtures takes
a minute or two and costs a small amount -- this is a deliberate
trade-off: a fake/mocked eval would be free and instant but wouldn't
actually tell you anything about real output quality.

Run this before and after any change to INTERPRETER_SYSTEM_PROMPT or
extract_dream_data's prompt in engine.py, and compare the two reports --
that's what turns "I think this prompt change is better" into "here's
the evidence."
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine  # noqa: E402
from fixtures import FIXTURES  # noqa: E402
from rubric import run_checks  # noqa: E402
from judge import judge_interpretation  # noqa: E402

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def run():
    results = []
    for i, fx in enumerate(FIXTURES, 1):
        print(f"[{i}/{len(FIXTURES)}] Running: {fx['id']} ({fx['lang']}) ...", flush=True)
        extracted = engine.extract_dream_data(fx["text"])
        interpretation = engine.interpret_dream(fx["text"], extracted)
        checks = run_checks(interpretation, fx["text"], lang=fx["lang"])
        judged = judge_interpretation(fx["text"], interpretation)
        results.append({
            "id": fx["id"],
            "lang": fx["lang"],
            "category": fx["category"],
            "checks": checks,
            "judge": judged,
            "interpretation": interpretation,
        })
    print_report(results)
    save_report(results)


def print_report(results):
    print("\n" + "=" * 90)
    header = f"{'id':<22}{'lang':<6}{'checks':<10}{'score':<8}{'failed checks / judge notes'}"
    print(header)
    print("-" * 90)

    total_score = 0
    scored_count = 0
    total_checks_passed = 0
    total_checks = 0

    for r in results:
        checks = r["checks"]
        passed = sum(1 for v in checks.values() if v is True)
        total = sum(1 for v in checks.values() if v is not None)
        total_checks_passed += passed
        total_checks += total

        score = r["judge"].get("score", 0)
        if score:
            total_score += score
            scored_count += 1

        failed = [k for k, v in checks.items() if v is False]
        note = ", ".join(failed) if failed else (r["judge"].get("reasoning", "")[:50])
        print(f"{r['id']:<22}{r['lang']:<6}{f'{passed}/{total}':<10}{score:<8}{note}")

    print("-" * 90)
    pct = (total_checks_passed / total_checks * 100) if total_checks else 0
    avg = (total_score / scored_count) if scored_count else 0
    print(f"Programmatic checks passed: {total_checks_passed}/{total_checks} ({pct:.0f}%)")
    print(f"Average judge score: {avg:.2f} / 5  (across {scored_count} scored fixtures)")
    print("=" * 90)

    # Call out anything that failed a check or scored low -- the summary
    # table above is easy to skim past, this isn't.
    flagged = [
        r for r in results
        if any(v is False for v in r["checks"].values()) or r["judge"].get("score", 5) <= 2
    ]
    if flagged:
        print(f"\n{len(flagged)} fixture(s) need a look:")
        for r in flagged:
            failed = [k for k, v in r["checks"].items() if v is False]
            print(f"  - {r['id']}: failed={failed or 'none'}, judge_score={r['judge'].get('score')}, "
                  f"judge_reasoning={r['judge'].get('reasoning')}")


def save_report(results):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"run_{int(time.time())}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nFull report (including every interpretation text) saved to {path}")


if __name__ == "__main__":
    run()
