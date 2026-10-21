"""
evals/judge.py -- LLM-as-judge scoring for interpretation quality.

rubric.py catches what's checkable with regex -- but "does this reading
actually feel specific and perceptive, or could it apply to almost any
dream" needs a reader's judgment, not a pattern match. This asks Claude
itself to read the original dream and Loominous's interpretation of it, side
by side, and score it the way a careful human reviewer would.

This is a separate, cheaper, more skeptical prompt than Loominous's own
interpretation voice (INTERPRETER_SYSTEM_PROMPT) on purpose -- a judge
that shares the exact same instincts as the thing it's judging is a bad
judge.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine  # noqa: E402  (path insert above has to come first)

JUDGE_SYSTEM_PROMPT = """You are a strict, skeptical quality reviewer for an AI
dream-interpretation app called Loominous. You are not the app itself -- you are
grading its output. Be honest and critical; a generic, vague, or templated
reading should score low even if it's well-written, and a specific,
perceptive one should score high even if it's imperfectly worded.

Score on this 1-5 scale:
5 -- specific to this exact dream, perceptive, nothing that could be
     copy-pasted onto a different dream unchanged.
4 -- mostly specific, one or two lines feel a little generic.
3 -- a reasonable mix of specific and generic -- an average reading.
2 -- mostly generic, could plausibly apply to several different dreams.
1 -- could be the response to almost any dream; no real engagement with
     this one's actual content.

Also flag, independent of the score:
- specific_not_generic: true if it engages with the dream's actual
  specific content rather than reciting dictionary-style symbol meanings.
- warm_tone: true if it reads as warm and like a caring friend, not
  clinical or academic.
- ends_cleanly: true if the response has a real ending (closing thought
  plus reflective question), false if it looks cut off mid-sentence.

Return STRICT JSON only, no markdown fences, no explanation outside the
JSON, in exactly this shape:
{"score": <1-5 integer>, "specific_not_generic": <bool>, "warm_tone": <bool>,
 "ends_cleanly": <bool>, "reasoning": "<one or two sentences on why>"}
"""


def judge_interpretation(dream_text, interpretation):
    """
    Score one interpretation against its original dream. Returns a dict
    with score/specific_not_generic/warm_tone/ends_cleanly/reasoning --
    falls back to a score of 0 with reasoning noting the failure if the
    judge call itself doesn't return parseable JSON, so one bad judge
    call doesn't crash a whole eval run.
    """
    prompt = f"""Dream as described by the person:
{dream_text}

Loominous's interpretation of it:
{interpretation}

Score this interpretation per the rubric in your instructions. Return
STRICT JSON only."""

    response = engine.client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=400,
        thinking={"type": "between_tools"},
        system=JUDGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = engine._extract_text(response)
    fallback = {
        "score": 0,
        "specific_not_generic": False,
        "warm_tone": False,
        "ends_cleanly": False,
        "reasoning": "judge call failed to return parseable output",
    }
    return engine._parse_json_safely(text, fallback)
