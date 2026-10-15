"""
Engine -- the AI layer of Loom. Four distinct jobs live here, kept
separate on purpose (this is "pipeline thinking" -- each stage does one
thing well, rather than one giant tangled function):

  1. EXTRACTION   -- turn a raw dream description into clean, structured
                      data (symbols, emotions, people, settings, themes).
  2. EMBEDDING     -- turn text into a lightweight "fingerprint" of its
                      meaningful words, so we can find dreams that share
                      symbols or themes even when worded differently.
  3. INTERPRETATION -- generate a grounded, universal-language reading of
                      a single dream (cross-cultural symbolism + dream
                      science, never religious, never literal prediction).
  4. PATTERN ANALYSIS -- look across the whole archive and reflect on
                      recurring themes and emotional trajectory over time.
"""

import json
import re
from dotenv import load_dotenv
import anthropic

load_dotenv()
client = anthropic.Anthropic()

# --- Embedding (lightweight, no ML model) --------------------------------
# This used to load a local sentence-transformers model, but that pulls in
# torch and can use 500MB+ of RAM just sitting idle -- too much for a small
# free-tier server. Instead, this reduces a dream to the set of its
# meaningful words (lowercased, punctuation stripped, common filler words
# removed). It won't catch two dreams that mean the same thing in totally
# different words, but it reliably catches recurring symbols, people, and
# settings -- which is what actually matters for a personal dream archive
# -- and it costs nothing: no model to download, no extra memory, no
# extra dependency.

_STOPWORDS = set("""
a about above after again against all am an and any are aren't as at be
because been before being below between both but by can't cannot could
couldn't did didn't do does doesn't doing don't down during each few for
from further had hadn't has hasn't have haven't having he he'd he'll he's
her here here's hers herself him himself his how how's i i'd i'll i'm
i've if in into is isn't it it's its itself let's me more most mustn't
my myself no nor not of off on once only or other ought our ours
ourselves out over own same shan't she she'd she'll she's should
shouldn't so some such than that that's the their theirs them themselves
then there there's these they they'd they'll they're they've this those
through to too under until up very was wasn't we we'd we'll we're we've
were weren't what what's when when's where where's which while who who's
whom why why's with won't would wouldn't you you'd you'll you're you've
your yours yourself yourselves dream dreamt dreaming
""".split())


def embed_text(text):
    """Turn a dream's text into a sorted list of its meaningful words --
    a stand-in "fingerprint" used to compare dreams to each other."""
    words = re.findall(r"[a-z']+", text.lower())
    meaningful = [w for w in words if w not in _STOPWORDS and len(w) > 2]
    return sorted(set(meaningful))


def cosine_similarity(vec_a, vec_b):
    """
    How similar two dreams' word-fingerprints are, from 0 (no shared
    words) to 1 (identical word sets). This is Jaccard similarity --
    the overlap between two sets divided by their combined size -- the
    simple-but-effective stand-in for real vector cosine similarity now
    that embeddings are just word sets instead of numeric vectors.
    """
    set_a, set_b = set(vec_a), set(vec_b)
    if not set_a or not set_b:
        return 0.0
    overlap = len(set_a & set_b)
    union = len(set_a | set_b)
    return overlap / union if union else 0.0


def find_similar_dreams(new_embedding, all_dreams, top_n=3):
    """
    Given a new dream's word-fingerprint and the full archive, return the
    top_n most similar past dreams by word overlap. Small, local, no
    external calls -- fine for a personal archive of this size.
    """
    scored = []
    for dream in all_dreams:
        if not dream["embedding"]:
            continue
        score = cosine_similarity(new_embedding, dream["embedding"])
        scored.append((score, dream))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    # Word overlap scores run lower than true semantic similarity scores,
    # so the "genuinely similar" bar is lower too -- tuned for this
    # simpler method rather than the 0.3 used for real embeddings.
    return [dream for score, dream in scored[:top_n] if score > 0.08]


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

Style -- be sharp and economical, not exhaustive:
- Say each idea once. Never restate the same point in a second sentence with
  different words just to sound fuller.
- Don't summarize or re-describe the dream back to the person -- they just told you
  what happened. Go straight to what it means.
- No filler or throat-clearing: skip phrases like "it's worth noting," "in many
  ways," "on a deeper level," "this is a powerful dream," or any sentence that
  exists only to transition rather than to say something.
- Prefer one well-chosen sentence over three vague ones. Cut any sentence that
  could be deleted without losing meaning.
- Every paragraph should earn its place. If you don't have 2-3 genuinely distinct
  things to say, write fewer paragraphs rather than padding to a target length.
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
Write the interpretation in this exact structure. Use light markdown -- it
gets rendered properly, so use it precisely as described, nothing extra:

1. Opening paragraph (2-4 sentences, plain text, no bold): the dream's overall
   symbolic read -- what it's fundamentally about, grounded in cross-cultural
   symbolism or dream science, stated plainly without hedging filler.
2. A blank line, then a short lead-in line like "Here's what stood out:"
3. One bullet line per notable symbol, emotion, or person actually present in
   the dream (3-5 bullets). Each bullet starts with "- **<element name>**:"
   (a hyphen, a space, the element in double asterisks, a colon), then one or
   two sentences on what it represents AND how it interacts with the other
   elements in this specific dream -- not a generic dictionary definition.
   Example:
   - **The unconscious brother**: ...
   - **Performing CPR**: ...
4. A blank line, then a closing paragraph (2-3 sentences, plain text, no
   bold) that ties the elements together into one coherent read of what this
   dream is doing psychologically right now.
5. A blank line, then one or two gentle, open questions on their own line(s)
   that invite the person to reflect further -- never a diagnosis, never a
   prediction of specific future events.

Do not use markdown anywhere except exactly as described above (bold only on
the bullet labels, "- " only for those bullets) -- no headers, no numbered
lists, no bold inside paragraphs.

Ground every bullet in the symbols, emotions, and people actually present in
this dream -- never generic statements that could apply to any dream. Total
length should land around 280-380 words, not counting the closing
question(s). Still follow the Style rules above: say each thing once, no
filler, no re-describing the dream back to the person.
"""
    response = client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=1100,
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
        max_tokens=500,
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

Write 2-3 warm, grounded paragraphs (roughly 150-220 words total) -- one point per
paragraph, nothing restated. Be honest if the data is too sparse or too similar in
timing to draw strong conclusions -- say so plainly, in one line, rather than
overstating a pattern.
"""
    response = client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=800,
        system=INTERPRETER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    return _extract_text(response)
