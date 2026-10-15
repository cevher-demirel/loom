"""
main.py -- Loom's FastAPI backend. The "front door" of the building.

Rooms in this building:
  POST /signup, POST /login  -- create or access an account
  POST /interpret             -- log a new dream, get back its reading
  GET  /dreams                 -- your archive, oldest-first summaries
  PUT  /dreams/{id}             -- edit a dream's text, re-interpret it
  DELETE /dreams/{id}           -- permanently remove a dream
  GET  /dreams/count           -- just the count
  GET  /patterns               -- cross-archive reflection
  POST /dreams/{id}/continue   -- keep talking about one specific dream
  GET  /profile, POST /profile -- who you are, so readings can be
                                  grounded in your actual life rather
                                  than staying generic
  GET  /health                 -- dependency status (no auth needed)

Every room except /signup and /login requires an Authorization header
("Bearer <token>") identifying who's asking, so each person's dreams,
conversations, and profile stay private to them. Nothing in engine.py
changes its own logic here -- this file is purely the door, the
corridors, and now the front desk that checks who's allowed in.

Run it with:
    uvicorn main:app --reload

Then open http://127.0.0.1:8000/docs in a browser -- FastAPI builds that
page for you automatically from this file. For any authenticated
endpoint, use "Try it out", add a header named "authorization" with the
value "Bearer <token>" (the token /signup or /login gave you), then
execute.
"""

import time

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import database
import engine
import observability
import vectorstore

# --- Startup -----------------------------------------------------------
database.init_db()

app = FastAPI(title="Loom")


# --- Structured request logging -------------------------------------------
# One JSON log line per request: method, path, status, total latency, and
# (when the request carried a valid token) which user -- see
# observability.py for why this is a JSON line and not a free-text one.
# This is deliberately separate from the per-stage logging inside
# /interpret and /continue below: this covers *every* endpoint, those two
# cover the handful of multi-step pipelines where "which stage was slow"
# actually matters.
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    request_id = observability.new_request_id()
    request.state.request_id = request_id

    user_id = None
    auth = request.headers.get("authorization")
    if auth and auth.startswith("Bearer "):
        try:
            user = database.get_user_by_token(auth[len("Bearer "):])
            user_id = user["id"] if user else None
        except Exception:
            pass  # never let a logging lookup break the actual request

    try:
        response = await call_next(request)
    except Exception as exc:
        observability.log_event(
            "request", request_id=request_id, method=request.method,
            path=request.url.path, user_id=user_id, status_code=500, ok=False,
            duration_ms=round((time.monotonic() - start) * 1000, 1),
            error=f"{type(exc).__name__}: {exc}",
        )
        raise

    observability.log_event(
        "request", request_id=request_id, method=request.method,
        path=request.url.path, user_id=user_id, status_code=response.status_code,
        ok=response.status_code < 400,
        duration_ms=round((time.monotonic() - start) * 1000, 1),
    )
    response.headers["X-Request-Id"] = request_id
    return response

# --- CORS ----------------------------------------------------------------
# The frontend (loom.html) is a separate static file that may be opened
# straight from disk, from GitHub Pages, or hosted somewhere else
# entirely -- not served by this app. Without this, a browser calling
# /interpret or /dreams from that page would be silently blocked by the
# browser's same-origin policy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Health -----------------------------------------------------------
# Unauthenticated on purpose -- a monitoring tool or Render's own health
# check needs to be able to call this without a token. Checks the actual
# dependencies (database, vector search) rather than just "the process
# is running" -- a process that's up but can't reach Turso is not
# actually healthy, and this is how you'd find that out without a user
# telling you first.
@app.get("/health")
def health():
    db_ok = database.ping()
    pinecone_status = vectorstore.ping()  # True / False / None (not configured)
    overall_ok = db_ok and pinecone_status is not False
    return {
        "ok": overall_ok,
        "database": "ok" if db_ok else "unreachable",
        "pinecone": (
            "not_configured" if pinecone_status is None
            else "ok" if pinecone_status else "unreachable"
        ),
    }


# --- Who's asking? -------------------------------------------------------

def get_current_user(authorization: str | None = Header(default=None)):
    """
    Every endpoint below except /signup and /login depends on this. The
    frontend sends 'Authorization: Bearer <token>' on every request
    after logging in; this pulls the token out, looks up the matching
    account, and 401s if it's missing, malformed, or doesn't match
    anyone (e.g. the account's token rotated because they logged in
    again somewhere else).
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not logged in")
    token = authorization[len("Bearer "):]
    user = database.get_user_by_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid -- please log in again")
    return user


# Same "genuinely similar, worth mentioning" bar the old in-memory search
# used (see engine.find_similar_dreams) -- kept here too so the Pinecone
# path applies the identical cutoff rather than returning its top_n
# matches unconditionally, however weakly related they actually are.
SIMILARITY_THRESHOLD = 0.3


def find_similar(user_id, embedding, exclude_dream_id=None, top_n=3):
    """
    Find dreams similar to a given embedding, scoped to one user.

    Uses the real vector database (vectorstore.py, backed by Pinecone)
    when PINECONE_API_KEY is configured -- a real approximate-nearest-
    neighbor search instead of looping over every dream in Python. Falls
    back to the original in-memory cosine search over everything pulled
    from Turso when Pinecone isn't configured (e.g. local dev without
    that key set yet), so this never hard-fails either way, it just
    degrades to the slower path.
    """
    if vectorstore.is_configured():
        matches = vectorstore.query_similar(
            user_id, embedding, top_n=top_n, exclude_dream_id=exclude_dream_id
        )
        similar_ids = [dream_id for dream_id, score in matches if score > SIMILARITY_THRESHOLD]
        similar = [database.get_dream(user_id, dream_id) for dream_id in similar_ids]
        return [d for d in similar if d is not None]

    all_dreams = database.get_all_dreams(user_id)
    if exclude_dream_id is not None:
        all_dreams = [d for d in all_dreams if d["id"] != exclude_dream_id]
    return engine.find_similar_dreams(embedding, all_dreams, top_n=top_n)


# --- Request / response shapes ------------------------------------------

class SignupIn(BaseModel):
    username: str
    password: str


class AuthOut(BaseModel):
    id: int
    username: str
    token: str


class DreamIn(BaseModel):
    raw_text: str


class DreamOut(BaseModel):
    id: int
    symbols: list[str]
    emotions: list[str]
    people: list[str]
    settings: list[str]
    themes: list[str]
    interpretation: str


class DreamSummary(BaseModel):
    # What the archive list sends back -- no embedding fingerprint,
    # nobody outside this building needs to see those. Includes the
    # conversation so the frontend can render each dream's existing
    # follow-up chat without a second request per dream.
    id: int
    timestamp: str
    raw_text: str
    symbols: list[str]
    emotions: list[str]
    themes: list[str]
    interpretation: str
    conversation: list[dict] = []


class PatternsOut(BaseModel):
    count: int
    analysis: str


class ContinueIn(BaseModel):
    message: str


class ContinueOut(BaseModel):
    reply: str
    conversation: list[dict]


class ChatTurn(BaseModel):
    role: str
    content: str


class ConversationIn(BaseModel):
    conversation: list[ChatTurn]


class ConversationOut(BaseModel):
    conversation: list[dict]


class ProfileIn(BaseModel):
    name: str = ""
    birth_year: int | None = None
    birthplace: str = ""
    current_location: str = ""
    bio: str = ""


class ProfileOut(BaseModel):
    name: str
    birth_year: int | None
    birthplace: str
    current_location: str
    bio: str


# --- Accounts --------------------------------------------------------------

@app.post("/signup", response_model=AuthOut)
def signup(payload: SignupIn):
    username = payload.username.strip()
    password = payload.password
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are both required")
    if len(password) < 4:
        raise HTTPException(status_code=400, detail="Password should be at least 4 characters")
    try:
        user = database.create_user(username, "", password)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return AuthOut(**user)


@app.post("/login", response_model=AuthOut)
def login(payload: SignupIn):
    user = database.authenticate_user(payload.username.strip(), payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Wrong username or password")
    return AuthOut(**user)


# --- Logging a dream ------------------------------------------------------

@app.post("/interpret", response_model=DreamOut)
def interpret(dream: DreamIn, request: Request, authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    raw_text = dream.raw_text.strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="raw_text cannot be empty")

    # Same pipeline as gui.py's on_interpret(), just called from a web
    # request instead of a button click -- scoped to this user's own
    # archive and profile, so the reading draws on their actual life
    # and their own past dreams, not anyone else's.
    #
    # Each stage is timed and logged separately (see observability.py) --
    # this is the thing Loom couldn't answer before Phase 3: if a /interpret
    # call is slow, which of these four steps actually took the time?
    rid = getattr(request.state, "request_id", None)
    profile = database.get_profile(user["id"])

    with observability.timed("pipeline_stage", request_id=rid, endpoint="/interpret", stage="extract"):
        extracted = engine.extract_dream_data(raw_text)
    with observability.timed("pipeline_stage", request_id=rid, endpoint="/interpret", stage="embed"):
        embedding = engine.embed_text(raw_text)
    with observability.timed("pipeline_stage", request_id=rid, endpoint="/interpret", stage="find_similar"):
        similar = find_similar(user["id"], embedding, top_n=3)
    with observability.timed("pipeline_stage", request_id=rid, endpoint="/interpret", stage="interpret"):
        interpretation = engine.interpret_dream(raw_text, extracted, similar, profile)

    with observability.timed("pipeline_stage", request_id=rid, endpoint="/interpret", stage="persist"):
        new_id = database.insert_dream(user["id"], raw_text, extracted, interpretation, embedding)
        # Index this dream's embedding in the vector database too (a no-op if
        # Pinecone isn't configured) -- done after the Turso insert so the
        # vector's dream_id metadata always points at a row that actually
        # exists.
        vectorstore.upsert_dream(user["id"], new_id, embedding)

    return DreamOut(
        id=new_id,
        symbols=extracted.get("symbols", []),
        emotions=extracted.get("emotions", []),
        people=extracted.get("people", []),
        settings=extracted.get("settings", []),
        themes=extracted.get("themes", []),
        interpretation=interpretation,
    )


@app.put("/dreams/{dream_id}", response_model=DreamOut)
def edit_dream(dream_id: int, dream: DreamIn, authorization: str | None = Header(default=None)):
    """
    Edit an already-logged dream's text and re-run the full pipeline on
    it -- a fresh extraction and a fresh interpretation, grounded in the
    corrected/expanded text rather than the original. The follow-up
    conversation on this dream is cleared (it was grounded in the old
    text and old reading, see database.update_dream), and the
    similarity search excludes this dream itself, so it never shows up
    as "similar to" its own past self.
    """
    user = get_current_user(authorization)
    raw_text = dream.raw_text.strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="raw_text cannot be empty")

    existing = database.get_dream(user["id"], dream_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="No dream with that id")

    profile = database.get_profile(user["id"])
    extracted = engine.extract_dream_data(raw_text)
    embedding = engine.embed_text(raw_text)
    similar = find_similar(user["id"], embedding, exclude_dream_id=dream_id, top_n=3)
    interpretation = engine.interpret_dream(raw_text, extracted, similar, profile)

    database.update_dream(user["id"], dream_id, raw_text, extracted, interpretation, embedding)
    # Overwrite this dream's vector with the new embedding -- same id, so
    # it replaces the old one rather than leaving a stale duplicate
    # behind in the index.
    vectorstore.upsert_dream(user["id"], dream_id, embedding)

    return DreamOut(
        id=dream_id,
        symbols=extracted.get("symbols", []),
        emotions=extracted.get("emotions", []),
        people=extracted.get("people", []),
        settings=extracted.get("settings", []),
        themes=extracted.get("themes", []),
        interpretation=interpretation,
    )


@app.delete("/dreams/{dream_id}")
def delete_dream(dream_id: int, authorization: str | None = Header(default=None)):
    """
    Permanently remove one dream from the archive, scoped to this
    user -- also removes its vector from Pinecone (vectorstore.delete_dream
    is a no-op if Pinecone isn't configured) so a deleted dream can't
    keep surfacing in similarity search after it's gone from Turso.
    """
    user = get_current_user(authorization)
    deleted = database.delete_dream(user["id"], dream_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="No dream with that id")
    vectorstore.delete_dream(user["id"], dream_id)
    return {"deleted": True}


# --- Reading the archive ---------------------------------------------------

@app.get("/dreams", response_model=list[DreamSummary])
def list_dreams(authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    all_dreams = database.get_all_dreams(user["id"])
    return [
        DreamSummary(
            id=d["id"],
            timestamp=d["timestamp"],
            raw_text=d["raw_text"],
            symbols=d["symbols"],
            emotions=d["emotions"],
            themes=d["themes"],
            interpretation=d["interpretation"],
            conversation=d.get("conversation", []),
        )
        for d in all_dreams
    ]


@app.get("/dreams/count")
def dream_count(authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    return {"count": database.count_dreams(user["id"])}


@app.get("/patterns", response_model=PatternsOut)
def patterns(authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    profile = database.get_profile(user["id"])
    all_dreams = database.get_all_dreams(user["id"])
    analysis = engine.analyze_patterns(all_dreams, profile)
    return PatternsOut(count=len(all_dreams), analysis=analysis)


# --- Continuing the conversation about one dream ---------------------------

@app.post("/dreams/{dream_id}/continue", response_model=ContinueOut)
def continue_dream(dream_id: int, payload: ContinueIn, request: Request, authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    rid = getattr(request.state, "request_id", None)
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    dream = database.get_dream(user["id"], dream_id)
    if dream is None:
        raise HTTPException(status_code=404, detail="No dream with that id")

    # The "seed" grounds every reply in the original dream and its first
    # reading -- rebuilt fresh each time from what's already stored,
    # rather than persisted itself, so the conversation column only ever
    # holds the actual back-and-forth that happened after that.
    seed = [
        {"role": "user", "content": f"My dream: {dream['raw_text']}"},
        {"role": "assistant", "content": dream["interpretation"]},
    ]
    conversation = dream.get("conversation") or []
    messages = seed + conversation + [{"role": "user", "content": message}]

    # A follow-up message can carry as much real signal as a freshly logged
    # dream -- more remembered detail, real-life context, even a whole
    # separate dream someone just thought of. Give it the same treatment a
    # new dream gets: ground it in the person's profile, and check it
    # against the rest of the archive (not just the one dream this thread
    # is attached to) so the reply can draw a genuine connection if there
    # is one.
    profile = database.get_profile(user["id"])
    with observability.timed("pipeline_stage", request_id=rid, endpoint="/continue", stage="embed"):
        message_embedding = engine.embed_text(message, input_type="query")
    with observability.timed("pipeline_stage", request_id=rid, endpoint="/continue", stage="find_similar"):
        related = find_similar(user["id"], message_embedding, exclude_dream_id=dream_id, top_n=3)
    with observability.timed("pipeline_stage", request_id=rid, endpoint="/continue", stage="reply"):
        reply = engine.continue_conversation(messages, profile=profile, related_dreams=related)

    conversation = conversation + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]
    database.update_dream_conversation(user["id"], dream_id, conversation)

    return ContinueOut(reply=reply, conversation=conversation)


@app.put("/dreams/{dream_id}/conversation", response_model=ConversationOut)
def replace_conversation(dream_id: int, payload: ConversationIn, authorization: str | None = Header(default=None)):
    """
    Overwrite a dream's whole follow-up conversation with exactly what's
    sent -- this is what powers editing or deleting a single message
    (and, deleting a user/assistant pair together): the frontend removes
    or changes an entry client-side and PUTs the resulting array back,
    rather than this needing a separate endpoint per kind of edit.
    """
    user = get_current_user(authorization)
    dream = database.get_dream(user["id"], dream_id)
    if dream is None:
        raise HTTPException(status_code=404, detail="No dream with that id")

    conversation = [turn.model_dump() for turn in payload.conversation]
    database.update_dream_conversation(user["id"], dream_id, conversation)
    return ConversationOut(conversation=conversation)


# --- Profile: who you are -----------------------------------------------

@app.get("/profile", response_model=ProfileOut)
def read_profile(authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    profile = database.get_profile(user["id"])
    return ProfileOut(
        name=profile["name"],
        birth_year=profile["birth_year"],
        birthplace=profile["birthplace"],
        current_location=profile["current_location"],
        bio=profile["bio"],
    )


@app.post("/profile", response_model=ProfileOut)
def write_profile(profile: ProfileIn, authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    database.save_profile(user["id"], profile.model_dump())
    return read_profile(authorization)
