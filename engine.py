"""
Engine -- the AI layer of Loom. Four distinct jobs live here, kept
separate on purpose (this is "pipeline thinking" -- each stage does one
thing well, rather than one giant tangled function):

  1. EXTRACTION   -- turn a raw dream description into clean, structured
                      data (symbols, emotions, people, settings, themes).
  2. EMBEDDING     -- turn text into a real semantic vector (via Voyage
                      AI), so we can find dreams that mean the same thing
                      even when worded completely differently.
  3. INTERPRETATION -- generate a grounded, universal-language reading of
                      a single dream (cross-cultural symbolism + dream
                      science, never religious, never literal prediction).
  4. PATTERN ANALYSIS -- look across the whole archive and reflect on
                      recurring themes and emotional trajectory over time.
"""

import json
import logging
import math
import re
import time
from dotenv import load_dotenv
import anthropic
import voyageai

import observability

load_dotenv()
client = anthropic.Anthropic()
voyage_client = voyageai.Client()  # reads VOYAGE_API_KEY from the environment
logger = logging.getLogger("loom.engine")


def _claude_call(stage, **kwargs):
    """
    Every Claude call in this file goes through here instead of calling
    client.messages.create directly, so none of them can quietly skip
    being logged. Logs one structured "claude_call" event: which stage
    of the app made the call (extract_dream_data, interpret_dream,
    continue_conversation, analyze_patterns), how long it took, and how
    many input/output tokens it used -- the two numbers that actually
    matter for debugging a slow request or an unexpectedly expensive
    one later.
    """
    start = time.monotonic()
    response = client.messages.create(**kwargs)
    duration_ms = round((time.monotonic() - start) * 1000, 1)
    usage = getattr(response, "usage", None)
    observability.log_event(
        "claude_call",
        stage=stage,
        model=kwargs.get("model"),
        duration_ms=duration_ms,
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
    )
    return response

# --- Embedding (real semantic vectors, via Voyage AI) ---------------------
# This used to be a stand-in: reduce a dream to the set of its meaningful
# words and compare word overlap. That's fast and free, but it only
# catches dreams that reuse the same words -- "I was drowning in the
# ocean" and "I was submerged underwater" would score as completely
# unrelated, despite meaning almost the same thing.
#
# Voyage AI's embedding API turns text into a real vector (a list of a
# few hundred floating-point numbers) that captures its *meaning*. Two
# dreams about similar themes end up with vectors that are mathematically
# close together -- measured with actual cosine similarity, the standard
# way to compare embeddings -- even when they don't share a single word.
# voyage-3.5-lite is used here: it's Voyage's fastest and cheapest model,
# plenty accurate for comparing short dream descriptions, and well within
# the free tier for a personal archive at this scale.

EMBEDDING_MODEL = "voyage-3.5-lite"


def embed_text(text, input_type="document"):
    """
    Turn a dream's text into a real semantic embedding vector via Voyage
    AI. input_type is Voyage's own hint for which side of a comparison
    this text is on ("document" for text being stored and later searched
    against, "query" for text doing the searching) -- it nudges the model
    toward slightly better vectors for that role, though both still live
    in the same comparable space. Returns an empty list on any API
    failure so a Voyage outage degrades the feature gracefully (dreams
    still save and interpret fine, they just won't surface "similar past
    dreams") instead of breaking dream logging entirely.
    """
    start = time.monotonic()
    try:
        result = voyage_client.embed(
            [text], model=EMBEDDING_MODEL, input_type=input_type
        )
        observability.log_event(
            "voyage_call", stage="embed_text", model=EMBEDDING_MODEL,
            input_type=input_type, ok=True,
            duration_ms=round((time.monotonic() - start) * 1000, 1),
            total_tokens=getattr(result, "total_tokens", None),
        )
        return result.embeddings[0]
    except Exception as exc:
        observability.log_event(
            "voyage_call", stage="embed_text", model=EMBEDDING_MODEL,
            input_type=input_type, ok=False,
            duration_ms=round((time.monotonic() - start) * 1000, 1),
            error=f"{type(exc).__name__}: {exc}",
        )
        return []


def cosine_similarity(vec_a, vec_b):
    """
    Real cosine similarity between two embedding vectors: the cosine of
    the angle between them, from -1 (opposite meaning) to 1 (identical
    meaning) -- 0 means unrelated. This is the standard way embeddings
    are compared; unlike word overlap, it works even when two dreams
    share no words at all but mean the same thing.
    """
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    try:
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
    except TypeError:
        # One of these is still an old word-list embedding (strings, not
        # numbers) rather than a real vector -- not comparable, treat as
        # unrelated rather than crashing.
        return 0.0
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_similar_dreams(new_embedding, all_dreams, top_n=3):
    """
    Given a new dream's embedding and the full archive, return the top_n
    most semantically similar past dreams. Dreams logged before this
    embedding model was swapped in are stored in the old word-list
    format (strings, not numbers) -- cosine_similarity's length/type
    checks make those score 0 and simply get skipped rather than
    crashing, so an existing archive keeps working without a migration;
    they'll start participating in similarity search again once
    re-interpreted.
    """
    if not new_embedding:
        return []
    scored = []
    for dream in all_dreams:
        if not dream["embedding"]:
            continue
        score = cosine_similarity(new_embedding, dream["embedding"])
        scored.append((score, dream))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    # Real embedding similarity runs on a different scale than word
    # overlap did -- topically related dreams typically land above ~0.3,
    # so that's the "genuinely similar, worth mentioning" bar here.
    return [dream for score, dream in scored[:top_n] if score > 0.3]


def _extract_text(response):
    """Pull the text out of a Claude response, skipping any thinking
    blocks -- the same pattern used throughout this whole project."""
    result = ""
    for block in response.content:
        if block.type == "text":
            result += block.text
    if not result:
        # This should be rare, but when it happens it's a silent failure
        # the person just sees as "nothing happened" -- log exactly what
        # came back (why generation stopped, and what block types the
        # response actually had) so it's diagnosable from Render's logs
        # instead of being invisible.
        block_types = [block.type for block in response.content]
        logger.warning(
            "Claude response had no text content -- stop_reason=%r block_types=%r",
            getattr(response, "stop_reason", None), block_types,
        )
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
  "symbols": ["list of 2-5 concrete symbols/objects/images in the dream -- each one
    distinct, never two entries for the same object (e.g. don't list both 'car'
    and 'brother's car' -- pick the one phrasing that captures it)"],
  "emotions": ["list of 1-3 emotions felt during or about the dream"],
  "people": ["list of people or figures that appeared, described generically if unnamed, e.g. 'a stranger', 'my mother'"],
  "settings": ["list of locations or settings the dream took place in"],
  "themes": ["list of 2-3 broader psychological or narrative themes, e.g. 'loss of control', 'transformation', 'being unprepared' -- each genuinely distinct, not two phrasings of the same idea"]
}}
"""
    response = _claude_call(
        "extract_dream_data",
        model="claude-sonnet-5-5",
        max_tokens=1024,
        thinking={"type": "between_tools"},
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

Your tone: warm first, always -- like a wise, caring friend who's genuinely glad they
told you this, not a clinician analyzing a case or an academic unpacking a symbol.
Speak to them directly as "you," not about "the dreamer" or "this person" in the
abstract. Let warmth show through word choice, not just content: favor words like
"carry," "hold," "tender," "gently," "makes sense that" over clinical ones like
"indicates," "represents a dynamic of," "suggests a pattern of." Where a feeling in
the dream was hard (fear, shame, confusion, grief), name it gently and with
compassion before analyzing it, so the person feels met, not studied. Still be a
little poetic and still grounded and clear -- warmth is not the same as vagueness.
Avoid vague horoscope-style language that could apply to anyone. Be specific to
what was actually described.

Style -- be sharp and economical, not exhaustive:
- Say each idea once. Never restate the same point in a second sentence with
  different words just to sound fuller.
- Don't summarize or re-describe the dream back to the person -- they just told you
  what happened. Go straight to what it means.
- No filler or throat-clearing: skip phrases like "it's worth noting," "in many
  ways," "on a deeper level," "this is a powerful dream," or any sentence that
  exists only to transition rather than to say something.
- Never open with "Across cultures," "Across many cultures," "In many
  traditions," or any variant of that phrase -- it has become a reflexive
  stock opener and reads as a template now. Start with whatever is actually
  most specific and interesting about THIS dream instead: a symbol, the
  emotion, the relationship, or the tension between two elements. Cross-
  cultural context can still inform what you say, it just can't be the
  first words of the reading.
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

Respond in the same language the dream was described in. The word-count
target above is approximate and is for English -- some languages need
noticeably more space to say the same thing, so treat it as a rough guide,
not a hard quota. It is far more important that the response ends cleanly
(the closing paragraph and the question(s) are both fully written) than
that it hits the top of the range -- if you're running long, shorten the
bullet explanations rather than risk being cut off before the ending.
"""
    response = _claude_call(
        "interpret_dream",
        model="claude-sonnet-5-5",
        max_tokens=2200,
        thinking={"type": "between_tools"},
        system=INTERPRETER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    return _extract_text(response)


CONTINUATION_SYSTEM_ADDENDUM = """
You're now in an ongoing conversation about one dream that's already been read
once. A few things matter here that didn't apply to the first reading:

- People often only remember more of the dream, or bring up the real-life
  context behind it, once they start talking about it. Treat each new message
  as potentially adding real information, not just a reaction to ask about --
  actually fold in what's new rather than repeating the original reading in
  different words.
- If what they share now sounds like a materially different or separate dream
  (a different night, a different scene, nothing really connecting it to the
  one you're discussing) rather than more of the same one, give it a genuine
  reading of its own first -- its own symbols, its own emotional read, grounded
  the same way a first interpretation would be, just in prose rather than the
  bulleted format. Do not force it into the frame of the dream this thread
  started on. After that real reading, mention that logging it as its own
  entry is what lets it get the full treatment and start counting toward
  their pattern analysis over time -- but the reading comes first, the
  suggestion is a footnote, not a redirect instead of engaging.
- If related dreams from their wider archive are listed below, you may draw a
  genuine connection to them -- only when it adds real insight, never as a
  forced callback just because the list exists.
- Match your reply's length to theirs. A short follow-up gets a short, warm
  reply -- don't pad it out just because you could say more.
"""


def continue_conversation(messages, profile=None, related_dreams=None):
    """
    Continue an ongoing dialogue about a specific dream. `messages` is the
    full conversation so far (starting with the original dream, then the
    first interpretation, then any back-and-forth since) -- the same
    pattern as a normal multi-turn chat, just grounded in one dream
    instead of starting fresh each time.

    profile grounds replies in the person's actual life, same as a first
    interpretation. related_dreams -- dreams from the archive that are
    semantically close to what the person just said in THIS message, not
    just the dream the thread started on -- is what lets someone who
    starts adding more context, or even describing another dream mid-chat,
    get a reply that's aware of their wider archive instead of treating
    the conversation as sealed off from everything else they've logged.
    """
    profile_block = _profile_context(profile)

    related_block = ""
    if related_dreams:
        descriptions = "\n".join(
            f"- ({d['timestamp'][:10]}): {', '.join(d['symbols'][:3])}"
            for d in related_dreams
        )
        related_block = f"""
Other dreams from this person's archive that are thematically close to what
they just said in this conversation:
{descriptions}
"""

    system = INTERPRETER_SYSTEM_PROMPT + "\n" + CONTINUATION_SYSTEM_ADDENDUM + profile_block + related_block

    response = _claude_call(
        "continue_conversation",
        model="claude-sonnet-5-5",
        max_tokens=1500,
        thinking={"type": "between_tools"},
        system=system,
        messages=messages
    )
    reply = _extract_text(response)
    if not reply:
        # _extract_text already logged the details. The person should
        # never see a chat bubble that's just... nothing -- that reads as
        # the app being broken, not as "try again." Give them something
        # visible and honest instead.
        reply = (
            "I didn't catch a reply there -- can you try sending that again?"
        )
    return reply


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
        line = (
            f"{date} -- symbols: {', '.join(d['symbols'])}; "
            f"emotions: {', '.join(d['emotions'])}; "
            f"themes: {', '.join(d['themes'])}"
        )
        # The follow-up chat on a dream is often where the real context
        # comes out -- the person pushing back on a reading, adding what
        # was actually going on in their life, correcting a guess. Only
        # their own messages go in here (the assistant's replies are just
        # Loom's own prior interpretation talking, not new information),
        # so patterns are read against what the person actually said about
        # their life, not just the dream's extracted tags.
        own_followups = [
            turn["content"] for turn in (d.get("conversation") or [])
            if turn.get("role") == "user"
        ]
        if own_followups:
            followup_text = " / ".join(own_followups)
            line += f"\n  follow-up context from this person: {followup_text}"
        summary_lines.append(line)
    archive_text = "\n".join(summary_lines)
    profile_block = _profile_context(profile)

    prompt = f"""{profile_block}Here is a chronological log of someone's dreams, each with extracted
symbols, emotions, and themes, plus anything they added afterward in a
follow-up conversation about that specific dream (real context about their
life, pushback on the reading, clarifications -- weigh this at least as
heavily as the extracted tags, since it's the person's own words):

{archive_text}

Look across this whole archive and reflect on:
1. Recurring symbols or themes, and what they might collectively point toward.
2. Any noticeable shift in emotional tone over time (e.g. from fear-dominant to
   more settled, or the reverse).
3. What direction this person's inner life genuinely seems to be moving in right
   now -- framed as trajectory and reflection, never as a prediction of specific
   future events. Ground this in anything concrete they shared in a follow-up,
   not just the dream content itself.

Format the answer as exactly three short sections, in this order, so someone can
scan it in a few seconds rather than read it as one block of prose. Each section
heading must be on its own line, wrapped in ** ** with nothing else on that line,
exactly like this:

**Recurring symbols & themes**
- one short, specific sentence
- one short, specific sentence (omit this second bullet if there's only one real
  thing to say)

**Emotional shift over time**
- one short, specific sentence
- one short, specific sentence

**Where this seems to be heading**
- one short, specific sentence
- one short, specific sentence

Every bullet is one sentence, concrete to this specific archive (names an actual
symbol, feeling, or thing they said in a follow-up -- never a generic line that
could apply to anyone's dreams). If the data is too sparse or too similar in
timing for a section to say anything real, that section gets exactly one bullet
saying so plainly instead of padding with a vague one. Total length stays short
(roughly 90-150 words across all three sections) -- this is a quick reflection,
not an essay.
"""
    response = _claude_call(
        "analyze_patterns",
        model="claude-sonnet-5-5",
        max_tokens=800,
        thinking={"type": "between_tools"},
        system=INTERPRETER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    return _extract_text(response)
