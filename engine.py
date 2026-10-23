"""
Engine -- the AI layer of Loominous. Four distinct jobs live here, kept
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
from datetime import datetime
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


# --- Agentic retrieval (search_dreams tool) --------------------------------
# analyze_patterns and continue_conversation used to get the archive handed
# to them in full up front -- every dream's tags (and, for patterns, every
# follow-up conversation) dumped into one prompt, whether or not the model
# ended up needing most of it. That's single-shot prompting: the model never
# decides what it needs, it just reacts to everything it was given.
#
# This tool lets the model ask for exactly the dreams it wants, when it
# wants them, mid-generation -- a short archive overview up front (dates,
# symbol/theme vocabulary only, no raw text) plus a loop that calls back
# into the app's own retrieval (Pinecone if configured, in-memory cosine
# search otherwise) whenever the model decides a claim needs checking
# against the actual dreams behind it.

SEARCH_DREAMS_TOOL = {
    "name": "search_dreams",
    "description": (
        "Search this person's dream archive for entries related to a symbol, "
        "theme, feeling, or description -- a semantic search, not a keyword "
        "match, so it finds dreams that mean the same thing even in different "
        "words. Returns each match's date, extracted symbols/emotions/themes, "
        "a snippet of the dream's own text, and anything the person added "
        "about it in a follow-up conversation. Use this whenever you're about "
        "to make a claim about the archive (a recurring symbol, an emotional "
        "shift, something the person mentioned before) that you haven't "
        "actually looked up yet -- don't guess from the overview alone."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "What to search for -- a symbol ('falling'), a theme "
                    "('conflict with a parent'), or a short description of a "
                    "dream to find similar ones to."
                ),
            },
            "top_n": {
                "type": "integer",
                "description": "How many matches to return. Defaults to 5.",
            },
        },
        "required": ["query"],
    },
}

MAX_TOOL_LOOP_ITERATIONS = 4  # a hard ceiling on back-and-forth per request --
# caps latency and cost if the model gets stuck re-querying instead of
# answering, rather than looping (and paying for Claude calls) indefinitely.


def _format_dream_for_tool(d):
    """
    Render one dream as a single line for a tool_result -- the same shape
    analyze_patterns used to inline for the whole archive, now built
    on-demand for just the dreams a search_dreams call actually returned.
    """
    date = (d.get("timestamp") or "")[:10]
    line = (
        f"{date} -- symbols: {', '.join(d.get('symbols') or [])}; "
        f"emotions: {', '.join(d.get('emotions') or [])}; "
        f"themes: {', '.join(d.get('themes') or [])}"
    )
    snippet = (d.get("raw_text") or "").strip()
    if snippet:
        line += f"\n  dream text: {snippet[:280]}"
    own_followups = [
        turn["content"] for turn in (d.get("conversation") or [])
        if turn.get("role") == "user"
    ]
    if own_followups:
        line += f"\n  follow-up context from this person: {' / '.join(own_followups)}"
    return line


def _run_tool_loop(stage, system, messages, search_fn, max_tokens):
    """
    Drive one multi-turn Claude conversation that may call search_dreams
    any number of times before producing its final answer. `messages` is
    mutated with each tool round-trip but is always a function-local copy
    (callers pass a fresh list), so this never corrupts a conversation
    history the caller still holds a reference to. Returns the model's
    final text, or a short, honest message if it never got there --
    search_fn is None (caller didn't wire one up, e.g. in a context that
    doesn't have per-user retrieval available) simply means the tool
    always comes back empty, which the model treats like any other
    archive with no matches.
    """
    for _ in range(MAX_TOOL_LOOP_ITERATIONS):
        response = _claude_call(
            stage,
            model="claude-sonnet-5-5",
            max_tokens=max_tokens,
            thinking={"type": "between_tools"},
            system=system,
            messages=messages,
            tools=[SEARCH_DREAMS_TOOL],
        )
        if response.stop_reason != "tool_use":
            return _extract_text(response)

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use" or block.name != "search_dreams":
                continue
            query = (block.input or {}).get("query", "")
            top_n = (block.input or {}).get("top_n") or 5
            try:
                matches = search_fn(query, top_n) if search_fn else []
            except Exception as exc:
                logger.warning("search_dreams tool call failed: %s: %s", type(exc).__name__, exc)
                matches = []
            observability.log_event(
                "tool_call", stage=stage, tool="search_dreams",
                query=query, top_n=top_n, result_count=len(matches),
            )
            result_text = (
                "\n".join(_format_dream_for_tool(d) for d in matches)
                if matches else "No matching dreams found in the archive."
            )
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_text,
            })
        messages.append({"role": "user", "content": tool_results})

    logger.warning("%s: tool loop hit %d iterations without a final answer", stage, MAX_TOOL_LOOP_ITERATIONS)
    return ""


def _run_tool_loop_stream(stage, system, messages, search_fn, max_tokens):
    """
    Same multi-turn search_dreams loop as _run_tool_loop, but streams
    text as Claude writes it instead of handing back one finished
    string. messages is mutated the same way _run_tool_loop's is; same
    caller contract (a fresh list per call).

    Each turn is opened with client.messages.stream, but its text_stream
    is buffered rather than forwarded live, and only released once that
    turn's stop_reason is known. thinking={"type": "between_tools"}
    routes most "let me check X first" reasoning into the thinking
    block rather than a visible text block, but Claude can still open a
    tool-calling turn with a short visible sentence alongside the tool
    call (seen in practice as a stray "Let me look at..." reaching the
    user) -- so a turn that ends in tool_use has its buffered text
    discarded instead of yielded. Only the turn that actually finishes
    the answer (stop_reason != "tool_use") gets its buffer released,
    chunk by chunk in the order it was received, which still streams
    normally for that final turn -- it just can't be relayed until that
    turn is known to be the last one.
    """
    for _ in range(MAX_TOOL_LOOP_ITERATIONS):
        start = time.monotonic()
        usage = None
        stop_reason = None
        final_content = None
        turn_text = []
        with client.messages.stream(
            model="claude-sonnet-5-5",
            max_tokens=max_tokens,
            thinking={"type": "between_tools"},
            system=system,
            messages=messages,
            tools=[SEARCH_DREAMS_TOOL],
        ) as stream:
            for text in stream.text_stream:
                turn_text.append(text)
            final_message = stream.get_final_message()
            usage = getattr(final_message, "usage", None)
            stop_reason = final_message.stop_reason
            final_content = final_message.content
        observability.log_event(
            "claude_call",
            stage=stage,
            model="claude-sonnet-5-5",
            duration_ms=round((time.monotonic() - start) * 1000, 1),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )
        if stop_reason != "tool_use":
            for text in turn_text:
                yield text
            return

        messages.append({"role": "assistant", "content": final_content})
        tool_results = []
        for block in final_content:
            if block.type != "tool_use" or block.name != "search_dreams":
                continue
            query = (block.input or {}).get("query", "")
            top_n = (block.input or {}).get("top_n") or 5
            try:
                matches = search_fn(query, top_n) if search_fn else []
            except Exception as exc:
                logger.warning("search_dreams tool call failed: %s: %s", type(exc).__name__, exc)
                matches = []
            observability.log_event(
                "tool_call", stage=stage, tool="search_dreams",
                query=query, top_n=top_n, result_count=len(matches),
            )
            result_text = (
                "\n".join(_format_dream_for_tool(d) for d in matches)
                if matches else "No matching dreams found in the archive."
            )
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_text,
            })
        messages.append({"role": "user", "content": tool_results})

    logger.warning("%s: tool loop hit %d iterations without a final answer", stage, MAX_TOOL_LOOP_ITERATIONS)


def _parse_json_safely(text, fallback):
    """
    LLMs sometimes wrap JSON in markdown fences or add stray words around
    it. This tries a clean parse first, falls back to finding the {...}
    block inside the text, and -- since a model occasionally breaks a
    string value across literal lines even when told not to, which is
    invalid JSON -- a last attempt that collapses raw newlines/tabs found
    *inside quoted strings* into spaces before parsing again. Only then
    does it give up and return the fallback, so a slightly messy response
    doesn't surface as "couldn't put together a reflection" more than it
    has to.
    """
    for candidate in (text.strip(), _extract_braces(text)):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except Exception:
            pass
        try:
            return json.loads(_collapse_newlines_in_strings(candidate))
        except Exception:
            pass
    return fallback


def _extract_braces(text):
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    return match.group(0) if match else None


def _collapse_newlines_in_strings(text):
    """Replace literal \\n/\\r/\\t characters that landed inside a JSON
    string's quotes with a single space, leaving everything outside quotes
    (the actual JSON structure) untouched."""
    out = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string and not escaped and ch in "\n\r\t":
            out.append(" ")
            continue
        out.append(ch)
        if ch == "\\" and not escaped:
            escaped = True
            continue
        if ch == '"' and not escaped:
            in_string = not in_string
        escaped = False
    return "".join(out)


# The closed set of icon names the symbol-card UI can actually draw (see
# index.html's ICON_SVGS). extract_dream_data assigns one of these -- or
# null -- to every entry in "symbols" (never "themes": the card row is
# deliberately literal-only, see symbols' own description below -- a
# concrete, nameable thing you could point at, not an abstract theme like
# "self-reliance and independence"), as a *judgment call about what the
# thing actually is*, not a keyword guess. A frontend-only keyword list
# kept missing ordinary dream content (a hot tub, a sibling, a bed) and,
# back when the card row still pulled in themes too, occasionally
# mismatched one to a literal icon just because it shared a substring with
# a keyword ("self-reliance and independence" once drew a mirror, from
# "self"). Asking the model to make this call directly, with a vocabulary
# it actually understands symbolically, is far more reliable than any
# string match.
#
# This list used to be a small hand-drawn set of ~29 broad buckets (door,
# house, vehicle, animal, ...), which meant a lot of ordinary dream nouns
# (a laptop, a van, a sunset, a horse, bread and cheese) had nothing
# accurate to land on and got forced into the nearest loose bucket or a
# wrong one entirely. These are instead real icon names from the Lucide
# icon set (lucide.dev, ISC licensed, MIT-compatible) -- a single
# consistent line-art style with enough everyday, literal nouns (specific
# animals, vehicles, foods, rooms, objects) that most things people
# actually dream about already have a real, accurate icon rather than a
# generic stand-in. Keep this list and index.html's ICON_SVGS keys in
# sync, using Lucide's own icon names (lucide.dev/icons) -- an
# unrecognized name is sanitized to null below, so a typo here just means
# that symbol loses its icon rather than breaking anything.
ICON_CATEGORIES = [
    'alarm-clock', 'anchor', 'apple', 'armchair', 'baby', 'backpack',
    'balloon', 'banana', 'bandage', 'banknote', 'bath', 'battery',
    'bed', 'beer', 'bike', 'bird', 'blinds', 'bomb',
    'book', 'book-open', 'brain', 'briefcase', 'bug', 'building',
    'building-2', 'bus', 'bus-front', 'cake', 'cake-slice', 'calendar',
    'camera', 'candy', 'car', 'car-front', 'caravan', 'carrot',
    'cat', 'cherry', 'chess-knight', 'clock', 'cloud', 'cloud-fog',
    'cloud-lightning', 'cloud-rain', 'cloud-snow', 'coffee', 'coins', 'compass',
    'cookie', 'credit-card', 'cross', 'crown', 'cup-soda', 'diamond',
    'dice-5', 'dog', 'door-closed', 'door-open', 'door-stairwell', 'droplet',
    'droplets', 'ear', 'egg', 'eye', 'feather', 'fence',
    'ferris-wheel', 'fish', 'fishing-hook', 'flag', 'flame', 'flame-kindling',
    'flashlight', 'flower', 'flower-2', 'footprints', 'forklift', 'fuel',
    'gem', 'ghost', 'gift', 'glasses', 'grape', 'hammer',
    'hand', 'heart', 'home', 'house', 'ice-cream-cone', 'key',
    'key-round', 'key-square', 'lamp', 'laptop', 'leaf', 'life-buoy',
    'lightbulb', 'lock', 'lock-open', 'luggage', 'mail', 'map',
    'medal', 'merge', 'milk', 'mirror-rectangular', 'mirror-round', 'monitor',
    'moon', 'moon-star', 'mountain', 'mountain-snow', 'newspaper', 'paintbrush',
    'palmtree', 'party-popper', 'paw-print', 'pen', 'pencil', 'person-standing',
    'phone', 'piggy-bank', 'pill', 'pizza', 'plane', 'plane-takeoff',
    'popcorn', 'puzzle', 'rabbit', 'rainbow', 'refrigerator', 'rocket',
    'rocking-chair', 'sailboat', 'sandwich', 'scissors', 'scooter', 'shell',
    'shield', 'ship', 'ship-wheel', 'shirt', 'shower-head', 'siren',
    'skull', 'smartphone', 'snail', 'snowflake', 'sofa', 'soup',
    'sparkle', 'sparkles', 'sprout', 'squirrel', 'star', 'stethoscope',
    'sun', 'sunrise', 'sunset', 'sword', 'syringe', 'table',
    'table-2', 'tent', 'tombstone', 'tractor', 'train', 'train-front',
    'trees', 'triangle-alert', 'trophy', 'truck', 'turtle', 'tv',
    'umbrella', 'umbrella-off', 'user', 'users', 'utensils', 'van',
    'wallet', 'warehouse', 'washing-machine', 'watch', 'waves', 'wheat',
    'wind', 'wine', 'worm', 'wrench', 'zap',
]


# Robert Plutchik's eight basic emotions -- a closed, real vocabulary
# (not invented for this app) rather than whatever free-text words an
# extraction happens to reach for. Used for exactly one thing:
# emotions_plutchik below, so the merged "What it carried" read (see
# renderEmotionMandala in index.html) can combine what someone tagged at
# entry with what the reading itself infers, on one shared vocabulary.
# The free-text "emotions" field above stays untouched and keeps its
# richer, more specific wording (e.g. "nostalgia", "dread") -- it's still
# what drives the tappable emotion chips elsewhere in the app.
#
# Sixteen words, not eight: Plutchik's own wheel pairs each of the eight
# primary emotions with its two neighbors to name eight further "dyad"
# emotions -- real, named blends from the same model, not an invented
# extension of it. Keeping both groups in one flat list here (the
# distinction only matters for how index.html lays them out around the
# wheel) is deliberate: a dream's tone is often one of these dyads
# outright (awe, contempt, remorse) rather than a pure primary.
PLUTCHIK_PRIMARY = ["Joy", "Trust", "Fear", "Surprise", "Sadness", "Disgust", "Anger", "Anticipation"]
PLUTCHIK_SECONDARY = ["Love", "Submission", "Awe", "Disapproval", "Remorse", "Contempt", "Aggressiveness", "Optimism"]
PLUTCHIK_EMOTIONS = PLUTCHIK_PRIMARY + PLUTCHIK_SECONDARY


def extract_dream_data(raw_text):
    """
    Ask Claude to read a dream description and pull out structured data.
    Returns a dict with symbols, emotions, people, settings, and themes
    (each a list of strings), plus symbol_icons: a {text: category} map
    covering every entry in symbols -- never themes, which stay abstract on
    purpose -- for the card UI (see ICON_CATEGORIES above). A card is only
    ever shown for a symbol that got a real category back, never a guessed
    or generic one.
    """
    icon_list = ", ".join(ICON_CATEGORIES)
    plutchik_list = ", ".join(PLUTCHIK_EMOTIONS)
    prompt = f"""Read this dream description and extract structured data from it.

Dream: {raw_text}

Return STRICT JSON only, no explanation, no markdown fences, with every string value on a single line (no literal line breaks inside quotes), in this exact shape:
{{
  "symbols": ["every concrete, literal symbol/object/image that actually carries weight in the dream -- things you could point at and name out loud (a door, a car, your brother, a hot tub), never an abstract idea or feeling. Include every one that genuinely qualifies, however many that turns out to be -- don't force a fixed count, pad the list to reach one, or leave a real one out just to keep it short. The ones the dream lingers on, repeats, or turns on, not just anything that happened to be in the scene. Skip incidental background detail (what someone was holding, a minor prop, ordinary furniture) unless the dream itself makes it central. Each one distinct, never two entries for the same object (e.g. don't list both 'car' and 'brother's car' -- pick the one phrasing that captures it)"],
  "emotions": ["list of 1-3 emotions felt during or about the dream"],
  "emotions_plutchik": ["1-3 of this dream's own emotional tone, picked ONLY from this fixed list (use these exact words, nothing else): {plutchik_list} -- pick whichever genuinely fit, even if that's just one, and prefer a more specific blend (e.g. 'Awe', 'Remorse', 'Contempt') over its two plainer parts when that's genuinely the closer read; this is a separate, stricter read from the free-text 'emotions' field above, not a rewording of it. ORDER THEM from most to least dominant in the dream -- never list two as equally strong just to avoid judging between them; there's almost always a clearer and a fainter one, and the order is read as that ranking, not an arbitrary list"],
  "people": ["list of people or figures that appeared, described generically if unnamed, e.g. 'a stranger', 'my mother'"],
  "settings": ["list of locations or settings the dream took place in"],
  "themes": ["list of 2-3 broader psychological or narrative themes, e.g. 'loss of control', 'transformation', 'being unprepared' -- each genuinely distinct, not two phrasings of the same idea. These are meant to stay abstract -- don't turn one into a literal object just so it has something concrete about it"],
  "symbol_icons": {{"one entry per item in the symbols list above ONLY -- never themes, which have nothing concrete to depict -- each key being that exact string": "the single best-fitting, most SPECIFIC icon name from this fixed list: {icon_list} -- prefer a specific match over a vague generic one when both are available (e.g. 'van' over 'car' for a camper van, 'sunset' over 'sun' for a sunset, 'sandwich' or 'wheat' over nothing for bread) -- or JSON null if none of them honestly fit that specific symbol (never force a weak match just to pick something)"}}
}}
"""
    response = _claude_call(
        "extract_dream_data",
        model="claude-sonnet-5-5",
        max_tokens=1536,
        thinking={"type": "between_tools"},
        messages=[{"role": "user", "content": prompt}]
    )
    text = _extract_text(response)
    fallback = {"symbols": [], "emotions": [], "emotions_plutchik": [], "people": [], "settings": [], "themes": [], "symbol_icons": {}}
    result = _parse_json_safely(text, fallback)
    icons = result.get("symbol_icons")
    result["symbol_icons"] = {
        k: v for k, v in icons.items() if v in ICON_CATEGORIES
    } if isinstance(icons, dict) else {}
    # Same discipline as symbol_icons just above: only keep values that are
    # actually in the fixed set, in case the model drifts from it slightly
    # (a near-miss word, different casing) -- a loose match here would
    # quietly break the apples-to-apples comparison this field exists for.
    plutchik = result.get("emotions_plutchik")
    result["emotions_plutchik"] = [
        e for e in plutchik if e in PLUTCHIK_EMOTIONS
    ] if isinstance(plutchik, list) else []
    return result


def classify_emotions_plutchik(raw_text, emotions_freetext=None):
    """
    A small, cheap classification-only pass used to backfill
    emotions_plutchik on a dream logged before that field existed (see
    main.py's GET /dreams/{id}/emotions). Maps what's already known
    about the dream -- its own text, plus whatever free-text emotions
    the original extraction already found -- onto the same fixed
    sixteen-word Plutchik set extract_dream_data uses, WITHOUT
    re-running the full extraction or re-interpreting the dream, so its
    stored text, reading, and conversation never change. A one-time
    cost per dream: main.py persists the result so this never runs
    twice for the same dream.
    """
    plutchik_list = ", ".join(PLUTCHIK_EMOTIONS)
    emotions_freetext = emotions_freetext or []
    context = ", ".join(emotions_freetext) if emotions_freetext else "none noted"
    prompt = f"""This dream was already read once, and its emotional tone was noted in free text as: {context}.

Dream: {raw_text}

Pick 1-3 words that best capture this dream's overall emotional tone, using ONLY this fixed list (these exact words, nothing else): {plutchik_list}. ORDER THEM from most to least dominant in the dream -- never list two as equally strong just to avoid judging between them; there's almost always a clearer and a fainter one, and the order is read as that ranking, not an arbitrary list.

Return STRICT JSON only, no explanation, no markdown fences, in this exact shape:
{{"emotions_plutchik": ["..."]}}
"""
    response = _claude_call(
        "classify_emotions_plutchik",
        model="claude-sonnet-5-5",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}]
    )
    text = _extract_text(response)
    result = _parse_json_safely(text, {"emotions_plutchik": []})
    plutchik = result.get("emotions_plutchik")
    return [e for e in plutchik if e in PLUTCHIK_EMOTIONS] if isinstance(plutchik, list) else []


INTERPRETER_SYSTEM_PROMPT = """You are the interpretation voice of Loominous, a dream
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


def _profile_context(profile, as_of_date=None):
    """
    Turn a profile dict into a short block of context text for prompts.
    Returns an empty string if the profile hasn't been filled in --
    interpretation should work fine with or without it.

    as_of_date: when given (a date, for a specific dream being
    interpreted), age is computed as of that date rather than today -- a
    dream backfilled from two years ago should say how old this person
    was back then, not how old they are right now. Callers reasoning
    across the whole archive at once (patterns, continuation) have no
    single date to pin this to, so they leave it as today, same as
    before this parameter existed.
    """
    if not profile:
        return ""

    reference_date = as_of_date or datetime.now().date()
    age_label = "Age at the time of this dream" if as_of_date else "Age"

    parts = []
    if profile.get("name"):
        parts.append(f"Name: {profile['name']}")
    # birth_date (an actual 'YYYY-MM-DD') gives an exact age; birth_year
    # is what an older profile saved before "Date of birth" replaced
    # "Birth year" in the UI still has on file, so it's kept as a
    # fallback rather than silently losing the only age signal those
    # profiles have. birth_date wins when both happen to be present.
    birth_date = profile.get("birth_date")
    if birth_date:
        try:
            born = datetime.strptime(birth_date, "%Y-%m-%d").date()
            age = reference_date.year - born.year - (
                (reference_date.month, reference_date.day) < (born.month, born.day)
            )
            parts.append(f"{age_label}: {age}")
        except ValueError:
            pass  # malformed date somehow got saved -- just omit age rather than crash a reading
    elif profile.get("birth_year"):
        age = reference_date.year - profile["birth_year"]
        parts.append(f"{age_label}: approximately {age}")
    if profile.get("gender"):
        parts.append(f"Gender: {profile['gender']}")
    if profile.get("relationship_status"):
        parts.append(f"Relationship status: {profile['relationship_status']}")
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


def _location_context(location, profile):
    """
    Where this specific dream was logged from, if the person set one --
    deliberately handed to the model with the opposite instinct from
    everything else in this file. Elsewhere, context is there to be used
    whenever it's genuinely relevant; here, the default is silence. Place
    is an easy, flashy thing for a model to reach for ("you were in
    Istanbul, this must be about roots") whether or not the dream itself
    actually earns that reading, and a reading that leans on it every time
    would feel gimmicky fast. So this only asks for a single understated
    note, and only when the dream's own content -- not just the fact that
    a location was logged -- genuinely resonates with it (e.g. it's
    clearly set somewhere other than, or specifically evokes, the place it
    was logged from). Most dreams should get no mention of place at all.
    """
    if not location:
        return ""
    birthplace = (profile or {}).get("birthplace")
    current = (profile or {}).get("current_location")
    reference = ""
    if birthplace or current:
        reference = (
            f" (for reference, this person is originally from {birthplace or 'unknown'} "
            f"and currently based in {current or 'unknown'})"
        )
    return (
        f"\nThis dream was logged while in: {location}{reference}. Only bring this "
        "into the reading if the dream's own content genuinely resonates with it -- "
        "e.g. it's clearly set in, or evokes, somewhere other than where it was "
        "logged from, which can sometimes point at something real about roots, "
        "belonging, or distance. If so, work it in as a single understated phrase "
        "inside an existing sentence, never its own paragraph, bullet, or headline "
        "claim. In most dreams this will have nothing to add -- say nothing about "
        "location at all rather than forcing a connection.\n"
    )


def _dream_date(dream_timestamp):
    """Parse a stored dream timestamp down to just its date, or None if
    there isn't one / it's malformed -- fail open rather than error out an
    interpretation over a timestamp parsing issue."""
    if not dream_timestamp:
        return None
    try:
        return datetime.fromisoformat(dream_timestamp).date()
    except ValueError:
        return None


def _time_context(dream_timestamp):
    """
    Tell the model when this dream actually happened relative to today,
    and how to calibrate its tense and framing accordingly.

    Without this, nothing in an interpretation prompt ever said what date
    the dream was from or what today's date is -- so a dream backfilled
    from two years ago got read exactly like one from last night, right
    down to the instructions explicitly asking for "what this dream is
    doing psychologically right now." That instruction is now dynamic:
    this function supplies the "right now" framing for a genuinely recent
    dream, and a "back then, in that chapter of their life" framing for
    an older one -- see the tense_note branches below.

    Returns a reasonable default (treat it as current) if no timestamp is
    available, so every caller of this always gets a valid Timing block
    to follow, never a dangling reference to guidance that isn't there.
    """
    dream_date = _dream_date(dream_timestamp)
    if dream_date is None:
        return (
            "\nTiming: treat this dream as something currently live in their life, "
            "and write about it in the present tense.\n"
        )

    today = datetime.now().date()
    days_ago = (today - dream_date).days

    if days_ago <= 3:
        recency = "right now -- today or within the last couple of days"
        tense_note = (
            "This is current: write about what this dream is doing psychologically "
            "right now, in the present tense, as something live in their life today."
        )
    elif days_ago <= 30:
        weeks = max(1, round(days_ago / 7))
        recency = f"recent -- about {weeks} week{'s' if weeks != 1 else ''} ago"
        tense_note = (
            "This is still recent: write about what it's doing psychologically right "
            "now, same as usual."
        )
    elif days_ago <= 365:
        months = max(1, round(days_ago / 30))
        recency = f"about {months} month{'s' if months != 1 else ''} ago"
        tense_note = (
            "This is no longer \"right now\" -- write about what this dream was doing "
            "psychologically for them back then, in that chapter of their life, rather "
            "than as something live in their life today. Only connect it to their "
            "present if the dream's own content genuinely still resonates now."
        )
    else:
        years = max(1, round(days_ago / 365))
        recency = f"about {years} year{'s' if years != 1 else ''} ago"
        tense_note = (
            "This is from a past chapter of their life, not the present -- write about "
            "what this dream was doing psychologically for them back then. Don't frame "
            "it as something live in their life today unless they've said it still is. "
            "It's fine, even fitting, to gently acknowledge the distance (e.g. \"looking "
            "back at this now\") rather than writing as if it just happened."
        )

    return (
        f"\nTiming: this dream happened on {dream_date.isoformat()} -- {recency} "
        f"(today is {today.isoformat()}). {tense_note}\n"
    )


def _build_interpret_prompt(raw_text, extracted, similar_dreams=None, profile=None, location=None, dream_timestamp=None, emotions_reported=None):
    """
    Builds the exact prompt interpret_dream sends to Claude. Pulled out on
    its own so interpret_dream and interpret_dream_stream (streaming
    version, same model and same words, just a different delivery
    mechanism -- see its docstring) can't quietly drift into sending two
    different prompts.
    """
    mood_context = ""
    if emotions_reported:
        mood_context = f"""
The dreamer themselves flagged this dream's felt sense as: {', '.join(emotions_reported)}.
Let that quietly color your tone and word choice -- it should shade how
you write, not become something you name or dwell on. Never quote these
words back or write a line like "you said you felt X", and don't let
them make the reading more literal or clinical about feelings than the
dream itself warrants; they're background weather, not a checklist to
confirm.
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

    time_block = _time_context(dream_timestamp)
    profile_block = _profile_context(profile, as_of_date=_dream_date(dream_timestamp))
    location_block = _location_context(location, profile)

    prompt = f"""{time_block}{profile_block}{location_block}Dream described: {raw_text}

Extracted data:
- Symbols: {', '.join(extracted.get('symbols', [])) or 'none noted'}
- Emotions: {', '.join(extracted.get('emotions', [])) or 'none noted'}
- People: {', '.join(extracted.get('people', [])) or 'none noted'}
- Settings: {', '.join(extracted.get('settings', [])) or 'none noted'}
- Themes: {', '.join(extracted.get('themes', [])) or 'none noted'}
{similar_context}{mood_context}
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
   dream was doing psychologically for them -- follow the Timing guidance
   above for whether to frame that as live in their life right now or as
   something from a past chapter of their life.
5. A blank line, then one or two gentle, open questions on their own line(s)
   that invite the person to reflect further -- phrased to fit the Timing
   guidance too (e.g. "what does this stir up" for something current,
   "what do you make of this, looking back" for something from the past) --
   never a diagnosis, never a prediction of specific future events.

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
    return prompt


def interpret_dream(raw_text, extracted, similar_dreams=None, profile=None, location=None, dream_timestamp=None, emotions_reported=None):
    """
    Generate a grounded, universal-language interpretation of a single
    dream. If similar_dreams is provided (from find_similar_dreams), the
    interpretation may gently note the recurrence -- this is what makes
    the archive feel connected over time, not just a list of one-offs.
    If profile is provided, the interpretation can draw on real context
    about who this person is and where they are in life. If location is
    provided (where this dream was logged from), see _location_context --
    it's meant to surface only rarely, not every time it's set.
    dream_timestamp (this dream's own logged date) lets the reading be
    calibrated to when it actually happened rather than always assuming
    "right now" -- see _time_context. emotions_reported (what the dreamer
    tagged at entry, see index.html's mood chips) is folded in as quiet
    tonal context only -- see _build_interpret_prompt's mood_context --
    never as something the reading names or checks off.

    This is the one stage slow enough (6-14s, measured) to actually be the
    bottleneck in /interpret -- see interpret_dream_stream below for the
    streaming version of the exact same call, used so the person sees
    words appear instead of a blank spinner for that whole stretch.
    """
    prompt = _build_interpret_prompt(raw_text, extracted, similar_dreams, profile, location, dream_timestamp, emotions_reported)
    response = _claude_call(
        "interpret_dream",
        model="claude-sonnet-5-5",
        max_tokens=2200,
        thinking={"type": "between_tools"},
        system=INTERPRETER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    return _extract_text(response)


def interpret_dream_stream(raw_text, extracted, similar_dreams=None, profile=None, location=None, dream_timestamp=None, emotions_reported=None):
    """
    Same prompt, same model, same output interpret_dream would produce --
    this just yields the text in pieces as Claude writes it, instead of
    handing back one finished string once the whole thing is done. Total
    generation time doesn't change; what changes is that a caller (see
    main.py's /interpret and the re-interpret path on PUT /dreams/{id})
    can start forwarding words to the person within a second or so,
    rather than making them watch a spinner for the full 6-14s this call
    can take. See interpret_dream's docstring for emotions_reported.
    """
    prompt = _build_interpret_prompt(raw_text, extracted, similar_dreams, profile, location, dream_timestamp, emotions_reported)
    start = time.monotonic()
    usage = None
    try:
        with client.messages.stream(
            model="claude-sonnet-5-5",
            max_tokens=2200,
            thinking={"type": "between_tools"},
            system=INTERPRETER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                yield text
            usage = getattr(stream.get_final_message(), "usage", None)
    finally:
        # Logged the same way _claude_call logs every other Claude call
        # (see its docstring) -- duration and token counts, so a slow or
        # expensive streamed call shows up in the logs exactly like a
        # non-streamed one does. In a `finally` so a call that errors or
        # gets cut off mid-stream still gets logged rather than vanishing.
        observability.log_event(
            "claude_call",
            stage="interpret_dream",
            model="claude-sonnet-5-5",
            duration_ms=round((time.monotonic() - start) * 1000, 1),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )


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


def continue_conversation(messages, profile=None, related_dreams=None, search_fn=None, dream_timestamp=None):
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
    dream_timestamp is the thread's own dream's logged date, same purpose
    as in interpret_dream -- a chat about a dream from two years ago
    shouldn't read as if it just happened last night.

    search_fn, if given, additionally lets the model call search_dreams
    mid-reply -- for when related_dreams (a one-shot embedding match on
    just this message) didn't surface something the person is explicitly
    referencing ("you mentioned falling before" should trigger an actual
    lookup, not a guess from whatever happened to be pre-fetched).
    """
    time_block = _time_context(dream_timestamp)
    profile_block = _profile_context(profile, as_of_date=_dream_date(dream_timestamp))

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

    tool_block = ""
    if search_fn:
        tool_block = (
            "\nIf the person references a past dream or pattern that isn't "
            "already covered above, use the search_dreams tool to actually "
            "look it up rather than guessing or asking them to repeat "
            "themselves.\n"
        )

    system = INTERPRETER_SYSTEM_PROMPT + "\n" + CONTINUATION_SYSTEM_ADDENDUM + time_block + profile_block + related_block + tool_block

    # _run_tool_loop appends tool round-trips to this list as it goes -- a
    # copy, so the caller's own conversation history (which only ever
    # stores plain {role, content} turns for display) never gets polluted
    # with tool_use/tool_result content blocks.
    reply = _run_tool_loop("continue_conversation", system, list(messages), search_fn, max_tokens=1500)
    if not reply:
        # _extract_text (inside the loop) already logged the details. The
        # person should never see a chat bubble that's just... nothing --
        # that reads as the app being broken, not as "try again." Give
        # them something visible and honest instead.
        reply = (
            "I didn't catch a reply there -- can you try sending that again?"
        )
    return reply


PATTERNS_TOO_FEW_DREAMS_MESSAGE = (
    "A few more dreams will help patterns come into view. "
    "Keep logging, and come back to this once you have at least "
    "3-5 entries."
)

PATTERNS_FALLBACK_MESSAGE = (
    "Couldn't put a reading together just now -- try again in a moment."
)


def _build_patterns_prompt(all_dreams, profile):
    """
    The prompt analyze_patterns and analyze_patterns_stream both send on
    their first turn -- pulled out so the two don't drift out of sync
    with each other. Caller is responsible for the len(all_dreams) < 3
    short-circuit; this assumes there's actually enough to index.

    Only a lightweight index of the archive (dates plus the vocabulary of
    symbols/emotions/themes that have come up) goes into the prompt up
    front -- not every dream's raw text and follow-up transcript, which
    used to be dumped in regardless of whether a given dream ended up
    mattering to the answer. search_fn, if given (see _run_tool_loop and
    _run_tool_loop_stream), lets the model pull up the real content (raw
    text, follow-up context) behind any symbol or theme it actually wants
    to ground a claim in, via the search_dreams tool -- so the archive
    scales without every call paying for the full text of every dream
    ever logged, and the model is reasoning from dreams it chose to look
    at rather than ones handed to it by default.
    """
    # The index: just enough for the model to spot candidates worth
    # investigating (what's recurring, roughly when) without any of the
    # per-dream detail that search_dreams exists to fetch on demand.
    index_lines = [
        f"{d['timestamp'][:10]}" + (f" ({d['location']})" if d.get('location') else "") +
        f" -- symbols: {', '.join(d['symbols'])}; "
        f"emotions: {', '.join(d['emotions'])}; themes: {', '.join(d['themes'])}"
        for d in all_dreams
    ]
    profile_block = _profile_context(profile)

    return f"""{profile_block}Here is a chronological index of someone's {len(all_dreams)} logged dreams --
just the date (and, when they set one, the place they were logging from) plus
the extracted symbols/emotions/themes for each, not the dream's own text or
anything they said about it afterward:

{chr(10).join(index_lines)}

Use this index to spot what looks recurring across symbols, emotions, or
themes, and to get a feel for ordering over time. Place is there in case it's
genuinely useful (e.g. a real shift in tone lining up with a move, or a
dream's content resonating with somewhere other than where it was logged
from) -- but most of the time it won't be the point, so only bring it up if
it's doing real explanatory work, never as a standing theme you mention in
every answer. Then, before writing anything about a specific recurring
symbol, theme, or emotional shift, use the search_dreams tool to pull up the
actual dreams behind it -- their real text and any follow-up context the
person added -- so the answer is grounded in what was actually said, not just
a tag that happened to repeat. Call it as many times as genuinely useful; a
pattern worth naming is usually worth checking against more than one dream.

Once you've looked into enough of the archive to answer honestly, reflect on:
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


def analyze_patterns(all_dreams, profile=None, search_fn=None):
    """
    Look across the entire dream archive and reflect on recurring
    patterns -- symbols, emotional shifts over time, and the person's
    apparent inner trajectory. Needs a handful of dreams to be meaningful;
    says so honestly if the archive is still too thin. If profile is
    provided, trajectory can be read against their actual real-life
    context (e.g. a major life transition), not just the dreams alone.
    See _build_patterns_prompt for how the prompt itself is built, and
    analyze_patterns_stream for the version main.py's /patterns endpoint
    actually calls now (same analysis, streamed as it's written).
    """
    if len(all_dreams) < 3:
        return PATTERNS_TOO_FEW_DREAMS_MESSAGE

    prompt = _build_patterns_prompt(all_dreams, profile)
    reply = _run_tool_loop(
        "analyze_patterns", INTERPRETER_SYSTEM_PROMPT,
        [{"role": "user", "content": prompt}], search_fn, max_tokens=800,
    )
    return reply or PATTERNS_FALLBACK_MESSAGE


def analyze_patterns_stream(all_dreams, profile=None, search_fn=None):
    """
    Same analysis as analyze_patterns -- same prompt, same search_dreams
    tool loop, same three-section answer -- but yields the final
    section's text in pieces as Claude writes it, instead of handing
    back one finished string once the whole multi-turn pass is done.
    See interpret_dream_stream's docstring for why that matters for a
    slow call; analyze_patterns is the single slowest one in the app (a
    multi-turn, tool-calling pass over the whole archive), so it's the
    one most worth not leaving someone staring at a spinner for.
    """
    if len(all_dreams) < 3:
        yield PATTERNS_TOO_FEW_DREAMS_MESSAGE
        return

    prompt = _build_patterns_prompt(all_dreams, profile)
    produced_any = False
    for piece in _run_tool_loop_stream(
        "analyze_patterns", INTERPRETER_SYSTEM_PROMPT,
        [{"role": "user", "content": prompt}], search_fn, max_tokens=800,
    ):
        produced_any = True
        yield piece
    if not produced_any:
        yield PATTERNS_FALLBACK_MESSAGE


def symbol_insight(symbol, occurrences):
    """
    A short reflection on one symbol or theme, grounded in the actual
    dreams of this person's own archive it came up in. occurrences is a
    list of {"date": "YYYY-MM-DD", "excerpt": "..."} for the dreams it
    appeared in (caller bounds how many; see main.py). Returns a dict with:

    - "teaser": one short, plain sentence for a small card -- no symbolic
      framing, no question, just what this symbol is doing in their
      dream(s), simply put.
    - "meaning": one to two sentences of real symbolic/archetypal
      grounding for THIS symbol specifically (the kind of thing a
      Jungian-influenced dream-work book would say about it -- thresholds
      for doors, the self's structure for a house, and so on), not a
      generic "dreams mean X" line, and not required to be flattering --
      if the honest symbolic reading has an edge or a complication, say so.
    - "direction": one short, direct question about how the symbol felt
      in THEIR dream specifically (not life-advice framed as "what part
      of your life...", just curiosity about their own experience of it).

    meaning and direction are written to read as one continuous reflection
    when shown together, not two disconnected lines.
    """
    occurrence_lines = "\n".join(
        f"- {o['date']}: \"{o['excerpt']}\"" for o in occurrences
    )
    prompt = f"""The symbol or theme "{symbol}" has come up in this person's own
dream archive, in these specific dreams:

{occurrence_lines}

Write a short reflection on "{symbol}" in two parts that read as one
continuous piece of writing:

1. A sentence or two of genuine symbolic grounding for "{symbol}" specifically
   -- the kind of thing a Jungian-influenced dream-work book would say about
   it (what it tends to represent archetypally: a threshold, a part of the
   self, a stage of individuation, etc. -- whatever actually fits this
   symbol). This part is allowed to be general dream-symbolism knowledge,
   not invented facts about this person -- but pick the reading that
   actually fits what's in the excerpts above, and don't force a positive
   spin if the more honest symbolic reading is more complicated or
   unsettled than that.
2. A short, direct question asking how the symbol actually FELT to them in
   the dream -- curiosity, unease, relief, something else -- never a
   "what part of your life" life-advice question, just genuine interest in
   their own experience of it.

Return STRICT JSON only, no explanation, no markdown fences, in this exact
shape (each value is plain prose on a single line -- no literal line breaks
inside the quotes, whatever it takes to keep the JSON valid):
{{
  "teaser": "one short, plain sentence with no symbolic framing and no question -- just what this symbol is doing in their dream(s), simple enough for a small card",
  "meaning": "1-2 sentences of symbolic/archetypal grounding, part 1 above",
  "direction": "one short feeling-question, part 2 above -- phrased so it reads as a natural continuation of the meaning sentence(s), not a separate non-sequitur"
}}
"""
    response = _claude_call(
        "symbol_insight",
        model="claude-sonnet-5-5",
        # 500 used to be the budget here, but this model spends some of its
        # own thinking tokens on every call (not just the ones that opt in
        # with `thinking=`), and that thinking competes with max_tokens for
        # the same budget. 500 was tight enough that a longer-than-usual
        # internal think (seen in practice with longer/non-English dream
        # excerpts) could burn the whole budget before any real "teaser"/
        # "meaning"/"direction" text came out at all -- stop_reason
        # "max_tokens" with zero text blocks, which is exactly what the
        # "Couldn't put together a reflection" fallback below was silently
        # catching. 1536 matches extract_dream_data's budget, which never
        # has this problem.
        max_tokens=1536,
        system=INTERPRETER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = _extract_text(response)
    fallback = {
        "teaser": "Couldn't put together a reflection on this just now -- try again in a moment.",
        "meaning": "",
        "direction": "",
    }
    return _parse_json_safely(text, fallback)


def symbol_chat_reply(symbol, occurrences, opening_reflection, conversation, message, profile=None):
    """
    Continue a conversation scoped to ONE symbol -- its own thread,
    separate from any single dream's chat, since the same symbol can
    turn up across many dreams and the conversation about it is one
    continuous thing rather than tied to whichever dream the person
    happened to tap into it from.

    occurrences is the same {"date", "excerpt"} list symbol_insight()
    takes. opening_reflection is the {"meaning", "direction"} this
    thread started from, seeded as the first assistant turn so the
    conversation never loses track of what it's actually responding to.
    conversation is the back-and-forth since then (plain {role, content}
    turns, same shape as a dream's conversation). No search_dreams tool
    here on purpose -- a symbol thread is meant to stay close to this one
    symbol and the dreams it already came from, not go fishing across the
    whole archive the way the main per-dream chat and pattern view do.
    """
    occurrence_lines = "\n".join(
        f"- {o['date']}: \"{o['excerpt']}\"" for o in occurrences
    )
    opening_text = (opening_reflection.get("meaning", "") + " " + opening_reflection.get("direction", "")).strip()
    profile_block = _profile_context(profile)

    system = (
        INTERPRETER_SYSTEM_PROMPT
        + "\n\nThis is a focused conversation about one specific symbol or "
        + f'theme from the person\'s dreams: "{symbol}". It showed up in these '
        + f"dreams of theirs:\n{occurrence_lines}\n\n"
        + f"The conversation opened with this reflection on it:\n{opening_text}\n\n"
        + profile_block
        + "\nKeep replies short (a few sentences at most) and grounded in "
        + f'"{symbol}" and the dreams above -- this is a focused follow-up '
        + "thread about one symbol, not a general dream chat."
    )

    seed = [
        {"role": "user", "content": f'Tell me what "{symbol}" might mean.'},
        {"role": "assistant", "content": opening_text},
    ]
    messages = seed + list(conversation) + [{"role": "user", "content": message}]

    # Same reasoning as symbol_insight's max_tokens above: 600 was tight
    # enough that this model's own internal thinking (not something this
    # call opts into -- it happens regardless) could burn the whole budget
    # before any reply text came out, which silently turned into "I didn't
    # catch a reply there". 1500 matches continue_conversation's budget,
    # which handles the same kind of multi-turn, possibly-multilingual
    # replies without this problem.
    reply = _run_tool_loop("symbol_chat_reply", system, messages, None, max_tokens=1500)
    if not reply:
        reply = "I didn't catch a reply there -- can you try sending that again?"
    return reply
