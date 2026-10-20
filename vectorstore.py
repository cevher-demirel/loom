"""
vectorstore.py -- the vector database layer, via Pinecone.

Dreams still live in Turso (database.py) -- that's the source of truth for
everything about a dream: its text, symbols, interpretation, conversation.
This file only stores and searches embeddings, the job
engine.find_similar_dreams() used to do entirely by itself: pull every
dream's embedding out of Turso and compare them one by one in Python.
That worked at personal-archive scale, but it isn't what a real retrieval
pipeline looks like -- a real one uses a vector database built for
exactly this, approximate nearest-neighbor search, rather than an
in-memory loop that gets slower the more dreams exist.

Pinecone is a fully managed, serverless vector database: no servers to
run yourself, just an API key and an index name. Each vector stored here
carries two pieces of metadata -- user_id (so one person's dreams are
never searched against another's) and dream_id (so a search result maps
back to an actual row in Turso, which is where the real dream content
still lives).

Degrades gracefully by design: every function here is a no-op (or
returns an empty result) if PINECONE_API_KEY isn't set, so an environment
that hasn't been given a Pinecone key yet -- a fresh local dev setup,
say -- still runs the whole app fine, it just doesn't get similarity
search until the key is added. is_configured() is how callers check
which situation they're in.
"""

import os
from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec

load_dotenv()

INDEX_NAME = "loom-dreams"
EMBEDDING_DIMENSION = 1024  # voyage-3.5-lite's default output_dimension

_api_key = os.environ.get("PINECONE_API_KEY")
_pc = Pinecone(api_key=_api_key) if _api_key else None
_index = None  # created lazily on first real use, see _get_index()


def is_configured():
    """Whether a PINECONE_API_KEY is actually set -- callers use this to
    decide whether to use the vector database or fall back to the older
    in-memory search."""
    return _pc is not None


def _get_index():
    """
    Returns the Pinecone index handle, creating the index itself on first
    use if it doesn't exist yet -- nothing to run by hand or provision in
    a dashboard first, the app just works the first time it's deployed
    with a Pinecone key. Cached after the first call so a fresh API
    request (listing every index that exists) doesn't happen on every
    single embed/search.
    """
    global _index
    if _pc is None:
        return None
    if _index is not None:
        return _index
    existing_names = [idx["name"] for idx in _pc.list_indexes()]
    if INDEX_NAME not in existing_names:
        _pc.create_index(
            name=INDEX_NAME,
            dimension=EMBEDDING_DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
    _index = _pc.Index(INDEX_NAME)
    return _index


def upsert_dream(user_id, dream_id, embedding):
    """
    Store (or, on a re-interpretation, overwrite) one dream's embedding.
    The vector id is "<user_id>:<dream_id>" so it's globally unique
    across every user sharing the same index, with user_id also stored
    as metadata so a query can filter to just one person's dreams without
    a second round trip. Silently does nothing if Pinecone isn't
    configured or the embedding is empty (embed_text() already degrades
    gracefully on a Voyage failure by returning [] -- this keeps that
    same promise one layer up rather than erroring on an empty vector).
    """
    index = _get_index()
    if index is None or not embedding:
        return
    index.upsert(vectors=[{
        "id": f"{user_id}:{dream_id}",
        "values": embedding,
        "metadata": {"user_id": user_id, "dream_id": dream_id},
    }])


def ping():
    """
    Cheap connectivity check for /health: True if Pinecone is configured
    and actually reachable right now, False if configured but the API
    call itself fails (wrong key, Pinecone outage, network issue --
    different from simply not being configured at all, which
    is_configured() already covers), None if not configured.
    describe_index_stats is used because it's a lightweight read that
    doesn't require the index to have any vectors in it.
    """
    if _pc is None:
        return None
    try:
        index = _get_index()
        index.describe_index_stats()
        return True
    except Exception:
        return False


def delete_dream(user_id, dream_id):
    """
    Remove a dream's vector. Not wired to anything yet -- Loom has no
    dream-delete feature today -- but exists so adding one later doesn't
    silently leave an orphaned vector behind in the index forever.
    """
    index = _get_index()
    if index is None:
        return
    index.delete(ids=[f"{user_id}:{dream_id}"])


def delete_user_dreams(user_id, dream_ids):
    """
    Remove every vector belonging to one user, as part of account
    deletion. Takes the caller's own list of dream_ids (from
    database.get_dream_ids()) rather than querying Pinecone for them,
    since Pinecone serverless indexes don't support "delete everything
    matching this metadata filter" the way pod-based ones used to --
    deleting by explicit id is the one operation guaranteed to work on
    every Pinecone plan. A no-op if Pinecone isn't configured or there's
    nothing to delete, same as every other function here.
    """
    index = _get_index()
    if index is None or not dream_ids:
        return
    index.delete(ids=[f"{user_id}:{dream_id}" for dream_id in dream_ids])


def query_similar(user_id, embedding, top_n=3, exclude_dream_id=None):
    """
    Real approximate-nearest-neighbor search, filtered to this one user's
    own dreams. Returns a list of (dream_id, score) tuples, most similar
    first. Deliberately returns just ids and scores, not full dream
    content -- Pinecone only ever stores the embedding, never the dream's
    actual text, so turning a dream_id back into a real dream record is
    the caller's job via database.get_dream(). That keeps this module a
    thin, dumb client around Pinecone rather than a second source of
    truth about what a dream actually says.
    """
    index = _get_index()
    if index is None or not embedding:
        return []
    # Ask for one extra result in case the dream being searched from
    # (e.g. re-interpreting an edited dream) is itself already in the
    # index and needs excluding -- done client-side here rather than via
    # a server-side $ne filter, since not every Pinecone plan supports
    # that filter operator, and this way works on all of them.
    result = index.query(
        vector=embedding,
        top_k=top_n + 1,
        filter={"user_id": {"$eq": user_id}},
        include_metadata=True,
    )
    matches = [
        (int(match["metadata"]["dream_id"]), match["score"])
        for match in result.get("matches", [])
        # Pinecone's metadata round-trips numbers as floats, so compare
        # against an int-cast exclude_dream_id rather than risk a
        # 5 != 5.0-style mismatch that would let the excluded dream
        # through.
        if exclude_dream_id is None or int(match["metadata"]["dream_id"]) != int(exclude_dream_id)
    ]
    return matches[:top_n]
