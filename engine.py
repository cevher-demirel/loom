"""
Engine -- the AI layer of Loom. Four distinct jobs live here, kept
separate on purpose (this is "pipeline thinking" -- each stage does one
thing well, rather than one giant tangled function):

  1. EXTRACTION   -- turn a raw dream description into clean, structured
                      data (symbols, emotions, people, settings, themes).
  2. EMBEDDING     -- turn text into a numeric vector that captures its
                      *meaning*, so we can find dreams that are thematically
                      similar even if they use completely different words.
  3. INTERPRETATION -- generate a grounded, universal-language reading of
                      a single dream (cross-cultural symbolism + dream
                      science, never religious, never literal prediction).
  4. PATTERN ANALYSIS -- look across the whole archive and reflect on
                      recurring themes and emotional trajectory over time.
"""

import json
import re
import numpy as np
from dotenv import load_dotenv
import anthropic

load_dotenv()
client = anthropic.Anthropic()

# --- Embedding model -----------------------------------------------------
# This runs locally on your own machine -- no API key, no per-call cost.
# It's loaded lazily (only the first time it's actually needed) because
# loading it takes a few seconds and we don't want that to slow app startup.
_embedding_model = None


def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        # all-MiniLM-L6-v2: small, fast, well-established general-purpose
        # embedding model. First run downloads it once (~90MB) and caches
        # it locally; every run after that is instant.
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedding_model


def embed_text(text):
    """Turn a piece of text into a semantic vector (a list of floats)."""
    model = get_embedding_model()
    vector = model.encode(text)
    return vector.tolist()


def cosine_similarity(vec_a, vec_b):
    """
    How similar two vectors are, from -1 (opposite meaning) to 1 (identical
    meaning). This is the standard way to compare embeddings -- it measures
    the *angle* between two vectors, not their raw distance, which turns
    out to capture semantic similarity well.
    """
    a = np.array(vec_a)
    b = np.array(vec_b)
    if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
        return 0.0
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def find_similar_dreams(new_embedding, all_dreams, top_n=3):
    """
    Given a new dream's embedding and the full archive, return the top_n
    most semantically similar past dreams. This is a small, local version
    of what a real vector database (like Pinecone) does at scale --
    the same underlying idea, just done with a simple loop since a
    personal dream archive will never be large enough to need more.
    """
    scored = []
    for dream in all_dreams:
        if not dream["embedding"]:
            continue
        score = cosine_similarity(new_embedding, dream["embedding"])
        scored.append((score, dream))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    # Only return genuinely similar dreams (score > 0.3), not just
    # whatever happens to rank highest among unrelated entries.
    return [dream for score, dream in scored[:top_n] if score > 0.3]


def _extract_text(response):
    """Pull the text out of a Claude response, skipping any thinking
    blocks -- the same pattern used throughout this whole project."""
    result = ""
    for block in response.content:
        if block.type == "text":
            result += block.text
    return result


def _parse_json_safely(text, fallback):
    """
    LLMs sometimes wrap JSON in markdown fences or add stray words around
    it. This tries a clean parse first, and falls back to finding the
    {...} block inside the text if that fails -- so a slightly messy
    response doesn't crash the whole app.
    """
    try:
        return json.loads(text.strip())
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return fallback
        return fallback


def extract_dream_data(raw_text):
    """
    Ask Claude to read a dream description and pull out structured data.
    Returns a dict with symbols, emotions, people, settings, and themes,
    each a list of strings.
    """
    prompt = f"""Read this dream description and extract structured data from it.

Dream: {raw_text}

Return STRICT JSON only, no explanation, no markdown fences, in this exact shape:
{{
  "symbols": ["list of concrete symbols/objects/images in the dream"],
  "emotions": ["list of emotions felt during or about the dream"],
  "people": ["list of people or figures that appeared, described generically if unnamed, e.g. 'a stranger', 'my mother'"],
  "settings": ["list of locations or settings the dream took place in"],
  "themes": ["list of 2-4 broader psychological or narrative themes, e.g. 'loss of control', 'transformation', 'being unprepared'"]
}}
"""
    response = client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    text = _extract_text(response)
    fallback = {"symbols": [], "emotions": [], "people": [], "settings": [], "themes": []}
    return _parse_json_safely(text, fallback)


INTERPRETER_SYSTEM_PROMPT = """You are the interpretation voice of Loom, a dream
reflection platform.

Your grounding, always:
- Cross-cultural symbolism and mythology -- the way certain images (water, flying,
  falling, being chased, teeth, houses, death, doors) recur across nearly every
  culture's dream traditions and folklore, not tied to any single religion.
- Modern dream science -- especially the continuity hypothesis (dreams often reflect
  what's emotionally active in waking life) and threat simulation theory (dreams
  often rehearse anxieties or unresolved situations).
- Jungian-style archetypal thinking, used loosely and accessibly, never as jargon.

Hard rules:
- NEVER claim to predict specific future events. Dreams do not foretell literal
  outcomes, and claiming otherwise would be dishonest.
- You CAN speak to trajectory -- the emotional or psychological direction a person's
  inner life seems to be moving in -- but always frame this as reflection, never
  certainty. Use language like "this often points toward..." or "this can suggest
  a readiness for..." never "this means you will..."
- Never invoke any specific religion, deity, or scripture. Keep the language entirely
  secular and universal, accessible to someone of any background or none at all.
- Never diagnose a mental health condition. If a dream describes something that
  suggests real distress, gently note that talking to someone they trust or a
  professional could help, without being alarmist.

Your tone: warm, thoughtful, a little poetic but still grounded and clear -- like a
wise, well-read friend, not a mystic and not a clinician. Avoid vague horoscope-style
language that could apply to anyone. Be specific to what was actually described.
"""


def _profile_context(profile):
    """
    Turn a profile dict into a short block of context text for prompts.
    Returns an empty string if the profile hasn't been filled in --
    interpretation should work fine with or without it.
    """
    if not profile:
        return ""

    parts = []
    if profile.get("name"):
        parts.append(f"Name: {profile['name']}")
    if profile.get("birth_year"):
        from datetime import datetime as _dt
        age = _dt.now().year - profile["birth_year"]
        parts.append(f"Age: approximately {age}")
    if profile.get("birthplace"):
        parts.append(f"Originally from: {profile['birthplace']}")
    if profile.get("current_location"):
        parts.append(f"Currently living in: {profile['current_location']}")
    if profile.get("bio"):
        parts.append(f"About their life: {profile['bio']}")

    if not parts:
        return ""

    return (
        "\nContext about this person (use it to ground the interpretation "
        "in their actual life where genuinely relevant -- never force a "
        "connection that isn't really there):\n" + "\n".join(parts) + "\n"
    )


def interpret_dream(raw_text, extracted, similar_dreams=None, profile=None):
    """
    Generate a grounded, universal-language interpretation of a single
    dream. If similar_dreams is provided (from find_similar_dreams), the
    interpretation may gently note the recurrence -- this is what makes
    the archive feel connected over time, not just a list of one-offs.
    If profile is provided, the interpretation can draw on real context
    about who this person is and where they are in life.
    """
    similar_context = ""
    if similar_dreams:
        descriptions = "\n".join(
            f"- ({d['timestamp'][:10]}): {', '.join(d['symbols'][:3])}"
            for d in similar_dreams
        )
        similar_context = f"""
This person has had thematically similar dreams before:
{descriptions}
If genuinely relevant, you may gently note this recurrence -- but only if it adds
real insight, not as a forced callback.
"""

    profile_block = _profile_context(profile)

    prompt = f"""{profile_block}Dream described: {raw_text}

Extracted data:
- Symbols: {', '.join(extracted.get('symbols', [])) or 'none noted'}
- Emotions: {', '.join(extracted.get('emotions', [])) or 'none noted'}
- People: {', '.join(extracted.get('people', [])) or 'none noted'}
- Settings: {', '.join(extracted.get('settings', [])) or 'none noted'}
- Themes: {', '.join(extracted.get('themes', [])) or 'none noted'}
{similar_context}
Write a grounded, universal-language interpretation of this dream, 3-5 short
paragraphs. Ground it in the symbols and emotions actually present, not generic
statements. End with one gentle, open question that invites the person to reflect
further on their own.
"""
    response = client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=1024,
        system=INTERPRETER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    return _extract_text(response)


def continue_conversation(messages):
    """
    Continue an ongoing dialogue about a specific dream. `messages` is the
    full conversation so far (starting with the original dream, then the
    first interpretation, then any back-and-forth since) -- the same
    pattern as a normal multi-turn chat, just grounded in one dream
    instead of starting fresh each time.
    """
    response = client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=1024,
        system=INTERPRETER_SYSTEM_PROMPT,
        messages=messages
    )
    return _extract_text(response)


def analyze_patterns(all_dreams, profile=None):
    """
    Look across the entire dream archive and reflect on recurring
    patterns -- symbols, emotional shifts over time, and the person's
    apparent inner trajectory. Needs a handful of dreams to be meaningful;
    says so honestly if the archive is still too thin. If profile is
    provided, trajectory can be read against their actual real-life
    context (e.g. a major life transition), not just the dreams alone.
    """
    if len(all_dreams) < 3:
        return ("A few more dreams will help patterns come into view. "
                 "Keep logging, and come back to this once you have at least "
                 "3-5 entries.")

    summary_lines = []
    for d in all_dreams:
        date = d["timestamp"][:10]
        summary_lines.append(
            f"{date} -- symbols: {', '.join(d['symbols'])}; "
            f"emotions: {', '.join(d['emotions'])}; "
            f"themes: {', '.join(d['themes'])}"
        )
    archive_text = "\n".join(summary_lines)
    profile_block = _profile_context(profile)

    prompt = f"""{profile_block}Here is a chronological log of someone's dreams, each with extracted
symbols, emotions, and themes:

{archive_text}

Look across this whole archive and reflect on:
1. Recurring symbols or themes, and what they might collectively point toward.
2. Any noticeable shift in emotional tone over time (e.g. from fear-dominant to
   more settled, or the reverse).
3. What direction this person's inner life genuinely seems to be moving in right
   now -- framed as trajectory and reflection, never as a prediction of specific
   future events.

Write 3-4 warm, grounded paragraphs. Be honest if the data is too sparse or too
similar in timing to draw strong conclusions -- say so plainly rather than
overstating a pattern.
"""
    response = client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=1536,
        system=INTERPRETER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    return _extract_text(response)
