"""
identity.py -- Stage 8 Phase B.2: server-side People identity-equivalence
validation.

Phase B.1 let the frontend send an `aliases` list alongside a symbol/
person label, so /symbols/insight and /symbols/chat could ground an AI
reflection on every dream a Phase B-merged identity actually represents
(see main.py's _symbol_occurrences). That request body was trusted
outright: whatever strings the caller sent were OR'd straight into the
match set. Nothing stopped a caller (a bug in a future client, or a
request crafted by hand) from passing unrelated aliases to broaden which
of this account's own dreams get treated as evidence for a completely
different identity -- never a CROSS-ACCOUNT leak (every match is still
scoped to database.get_all_dreams(user_id), so another account's dreams
are never reachable this way), but a same-account integrity problem: an
"insight" and chat thread labeled "Abby" could end up grounded on dreams
that have nothing to do with Abby at all.

This module is a small, independent, pure-function re-derivation of
whether one raw People mention is a legitimate equivalent of a resolved
identity, computed fresh from this account's own authoritative data (its
dreams' own `people` fields, plus its own saved person_identity_links
corrections) -- never from anything a caller merely asserts. It mirrors
index.html's buildPersonIdentityIndex/resolvePersonMention (the Phase B/
B.1 resolution rules) closely enough to validate the exact aliases that
algorithm would legitimately produce, but it is deliberately NOT a
byte-for-byte port: it only needs to answer "does this one raw mention
resolve to this one target identity," not render a map. Kept in parity
with the real JS behavior by tests/test_identity_parity.py, which runs
representative fixtures through both implementations and asserts they
agree -- the two-implementations-could-drift risk Phase B.1 avoided by
NOT doing this is managed here by testing for drift directly, since
Phase B.2 explicitly calls for validating aliases against the user's own
data rather than trusting the client's claim.

Equivalence contract (same two rules as Phase B, applied the same way
Phase B.1 applies a saved correction):
  1. A bare role mention ("brother" / "my brother") is equivalent to a
     resolved name only when exactly one name has ever been paired with
     that role across this account's own dreams ("brother James" and
     nothing else for "brother") -- never when 0 or 2+ candidates exist.
     An indefinite-article mention ("a stranger") is never part of this
     at all, same as Phase B.
  2. A role term immediately followed by a name ("girlfriend Abby")
     names that person directly.
  3. A saved person_identity_links row always wins over rule 1: a
     'separate' decision forces a role bucket to resolve as itself (even
     with exactly one named candidate); a 'merge' decision forces it (or
     a plain name) to resolve as its chosen target instead.
If an alias doesn't resolve to the requested identity under these rules,
it is dropped -- silently, from the server's point of view (the request
still succeeds with whatever subset of aliases DID validate), never
accepted on good faith. This is the conservative, fail-closed behavior
the brief asks for where full equivalence can't otherwise be verified:
an alias that depends on something this function can't see (for example
a legitimate account-wide merge the frontend computed that doesn't
reduce to these rules) is simply not used for grounding, rather than
trusted anyway.
"""
import re
import unicodedata

PERSON_ROLE_TERMS = [
    "mother", "mom", "mum", "father", "dad", "papa",
    "brother", "sister", "sibling",
    "wife", "husband", "spouse", "partner", "fiancee", "fiance",
    "girlfriend", "boyfriend",
    "ex-girlfriend", "ex-boyfriend", "ex-wife", "ex-husband", "ex",
    "grandmother", "grandma", "grandfather", "grandpa",
    "cousin", "aunt", "uncle", "niece", "nephew",
    "son", "daughter", "child",
    "friend", "best friend",
    "coworker", "colleague", "boss", "manager", "teacher", "professor",
    "neighbor", "neighbour", "roommate", "classmate",
]
# Longest phrase first, same reasoning as index.html's
# PERSON_ROLE_TERMS_SORTED -- "ex-girlfriend" must be tried before the
# bare "ex" it would otherwise be swallowed by.
PERSON_ROLE_TERMS_SORTED = sorted(PERSON_ROLE_TERMS, key=len, reverse=True)
PERSON_ROLE_TERMS_SET = set(PERSON_ROLE_TERMS)

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_tag_key(raw):
    """Same normalization index.html's normalizeTagKey applies: NFKC,
    curly quotes to straight, collapsed whitespace, trimmed, lowercased."""
    s = unicodedata.normalize("NFKC", str(raw) if raw is not None else "")
    s = s.replace("‘", "'").replace("’", "'").replace("ʼ", "'")
    s = s.replace("“", '"').replace("”", '"')
    s = _WHITESPACE_RE.sub(" ", s).strip().lower()
    return s


def strip_my_prefix(normalized_key):
    return normalized_key[3:] if normalized_key.startswith("my ") else normalized_key


def parse_person_mention(raw):
    """Mirrors index.html's parsePersonMention. Returns one of:
    {"kind": "role", "role_term"}
    {"kind": "named-role", "role_term", "name"}
    {"kind": "name", "name"}
    """
    norm = normalize_tag_key(raw)
    core = strip_my_prefix(norm)
    if core in PERSON_ROLE_TERMS_SET:
        return {"kind": "role", "role_term": core}
    for role_term in PERSON_ROLE_TERMS_SORTED:
        prefix = role_term + " "
        if core.startswith(prefix):
            name_part = core[len(prefix):].strip()
            if name_part:
                return {"kind": "named-role", "role_term": role_term, "name": name_part}
    return {"kind": "name", "name": core}


def build_role_resolution(people_lists):
    """people_lists: an iterable of this account's own dreams' raw
    `people` lists. Mirrors index.html's buildPersonIdentityIndex, minus
    nameDisplayFromBare (display labels aren't needed for validation).
    Returns {role_term: resolved_name_or_None}."""
    role_candidate_names = {}
    for people in people_lists:
        for raw in (people or []):
            if not raw or not str(raw).strip():
                continue
            mention = parse_person_mention(raw)
            if mention["kind"] == "named-role":
                role_candidate_names.setdefault(mention["role_term"], set()).add(mention["name"])
    role_resolution = {}
    for role_term, names in role_candidate_names.items():
        role_resolution[role_term] = next(iter(names)) if len(names) == 1 else None
    return role_resolution


def resolve_person_key(raw, role_resolution, overrides):
    """Mirrors index.html's resolvePersonMention. `overrides` is this
    account's own saved person_identity_links rows, as a dict keyed by
    subject_key -> {"decision": "merge"|"separate", "target_key": str}.
    Returns the resolved identity key this one raw mention would produce
    -- "abby", "role:brother", etc. Never raises on malformed input;
    worst case for a non-string/empty raw is resolving to an empty-string
    key, which will simply never equal a real symbol_key."""
    overrides = overrides or {}
    mention = parse_person_mention(raw)

    if mention["kind"] in ("name", "named-role"):
        natural_key = mention["name"]
        override = overrides.get(natural_key)
        if override and override.get("decision") == "merge" and override.get("target_key"):
            return override["target_key"]
        return natural_key

    role_bucket_key = "role:" + mention["role_term"]
    override = overrides.get(role_bucket_key)
    if override and override.get("decision") == "separate":
        return role_bucket_key
    if override and override.get("decision") == "merge" and override.get("target_key"):
        return override["target_key"]

    resolved_name = role_resolution.get(mention["role_term"])
    if resolved_name:
        name_override = overrides.get(resolved_name)
        if name_override and name_override.get("decision") == "merge" and name_override.get("target_key"):
            return name_override["target_key"]
        return resolved_name

    return role_bucket_key


def validate_person_aliases(symbol_key, aliases, dreams, identity_links):
    """
    The one function main.py calls. Returns the subset of `aliases` that
    genuinely, verifiably resolve to `symbol_key` under this account's
    own dreams and saved corrections -- never the raw input handed back
    unchecked. `dreams` is this user's own database.get_all_dreams(...)
    result; `identity_links` is this user's own
    database.list_person_identity_links(...) result. Both must already
    be scoped to the authenticated user by the caller -- this function
    does no authorization of its own, it only computes equivalence
    within whatever data it's given.
    """
    if not aliases:
        return []
    role_resolution = build_role_resolution(d.get("people") for d in (dreams or []))
    overrides = {
        row["subject_key"]: row
        for row in (identity_links or [])
        if isinstance(row, dict) and row.get("subject_key")
    }
    valid = []
    for alias in aliases:
        if not isinstance(alias, str):
            continue
        alias_norm = alias.strip().lower()
        if not alias_norm:
            continue
        if resolve_person_key(alias_norm, role_resolution, overrides) == symbol_key:
            valid.append(alias_norm)
    return valid
