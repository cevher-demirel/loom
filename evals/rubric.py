"""
evals/rubric.py -- the programmatic (no API call, free, instant) half of
the eval harness. Catches the mechanical stuff that regex can check
reliably: the things Loom has actually gotten wrong before.

The LLM-as-judge in judge.py handles the squishier half (is this reading
actually specific and perceptive, or could it apply to any dream) --
these two together are the eval harness.

run_checks() returns a dict of check_name -> True/False/None. None means
"not applicable to this fixture" (e.g. the structure check is skipped for
non-English fixtures, since the format can reasonably flex there) rather
than a failure.
"""

import re

STOCK_OPENERS = (
    "across cultures",
    "across many cultures",
    "in many cultures",
    "in many traditions",
    "throughout history",
    "throughout many cultures",
)

# Deliberately simple, word-boundary matches -- this is a smoke test, not
# a perfect classifier. False negatives are fine; a false positive (e.g.
# matching "god" inside "good") is the thing to avoid, hence \b everywhere.
RELIGIOUS_TERMS = (
    r"\ballah\b", r"\bjesus\b", r"\bchrist\b", r"\bbuddha\b", r"\bkrishna\b",
    r"\bbible\b", r"\bquran\b", r"\bkoran\b", r"\btorah\b", r"\bgod\b",
    r"\bgod's will\b", r"\bdivine judgment\b",
)

# Deterministic-future-prediction phrasing -- the hard rule in
# INTERPRETER_SYSTEM_PROMPT is "never claim to predict specific future
# events." These are the phrasings that would actually cross that line;
# softer language like "can suggest" or "often points toward" is fine and
# deliberately not flagged here.
PREDICTION_PHRASES = (
    "this means you will", "this predicts", "you are going to die",
    "you will die", "this is a sign that you will", "you will definitely",
)


def _starts_with_stock_opener(text):
    opening = text.strip().lower()[:60]
    return any(opening.startswith(p) for p in STOCK_OPENERS)


def _has_bullet_breakdown(text):
    # Expects lines like "- **Something**: explanation" -- at least 3,
    # matching interpret_dream's prompt (3-5 bullets).
    bullets = re.findall(r"^- \*\*.+?\*\*:", text, flags=re.MULTILINE)
    return len(bullets) >= 3


def _ends_with_question(text):
    tail = text.strip()
    if not tail:
        return False
    # The closing question(s) should be the last thing in the response --
    # look at the last non-empty line.
    last_line = [ln for ln in tail.splitlines() if ln.strip()][-1]
    return last_line.strip().endswith("?")


def _ends_cleanly(text):
    # A truncated response (the token-budget bug this caught before) ends
    # mid-word or mid-sentence, not on normal closing punctuation.
    tail = text.strip()
    if not tail:
        return False
    return tail[-1] in ".?!…”\"'"


def _no_religious_language(text):
    lowered = text.lower()
    return not any(re.search(pattern, lowered) for pattern in RELIGIOUS_TERMS)


def _no_literal_prediction(text):
    lowered = text.lower()
    return not any(phrase in lowered for phrase in PREDICTION_PHRASES)


def _reasonable_length(text, lang):
    word_count = len(text.split())
    if lang != "en":
        # Non-English text can legitimately need more words for the same
        # content (this is exactly what the Turkish-truncation bug was
        # about) -- just check it's not suspiciously short, which would
        # mean it got cut off, rather than holding it to the English
        # target at all.
        return word_count >= 80
    return 150 <= word_count <= 500


def run_checks(interpretation, dream_text, lang="en"):
    """
    Run every programmatic check against one interpretation. Returns a
    dict of check_name -> bool. Always run this even when the LLM judge
    is also run -- it's free and instant, so there's no reason to skip it.
    """
    return {
        "no_stock_opener": not _starts_with_stock_opener(interpretation),
        "has_bullet_breakdown": _has_bullet_breakdown(interpretation),
        "ends_with_question": _ends_with_question(interpretation),
        "ends_cleanly": _ends_cleanly(interpretation),
        "no_religious_language": _no_religious_language(interpretation),
        "no_literal_prediction": _no_literal_prediction(interpretation),
        "reasonable_length": _reasonable_length(interpretation, lang),
    }
