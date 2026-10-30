"""
main.py -- Loominous's FastAPI backend. The "front door" of the building.

Rooms in this building:
  POST /signup, POST /login  -- create or access an account (login
                                 accepts a username or an email)
  POST /logout                 -- invalidate the calling token server-side
  POST /forgot-password        -- request a password-reset email
  POST /reset-password          -- actually set the new password
  GET  /account                 -- who's logged in, and whether their
                                   email is confirmed yet
  DELETE /account                -- permanently delete the calling
                                     account and everything in it
  POST /verify-email            -- confirm an email from its emailed link
  POST /resend-verification     -- send another confirmation email
  POST /account/email           -- add/change the email on file (e.g. a
                                   legacy account that never had one)
  POST /interpret             -- log a new dream, get back its reading
  GET  /dreams                 -- your archive, oldest-first summaries
  PUT  /dreams/{id}             -- edit a dream's text, re-interpret it
  PUT  /dreams/{id}/date        -- backdate a dream to an earlier night
  PUT  /dreams/{id}/location    -- set/clear where a dream was from
  DELETE /dreams/{id}           -- permanently remove a dream
  GET  /dreams/count           -- just the count
  GET  /patterns               -- cross-archive reflection
  POST /symbols/insight         -- a grounded reflection on one symbol/theme
  GET  /symbols/chat             -- one symbol's own conversation thread
  POST /symbols/chat             -- keep talking about one specific symbol
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

import concurrent.futures
import hashlib
import json
import os
import re
import time
from datetime import datetime

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import database
import emailer
import engine
import observability
import ratelimit
import vectorstore

# Where the browser frontend (index.html) is actually reachable, so a
# password-reset email can link back to it. Not every deployment has
# this hosted anywhere public yet -- when it's unset, /forgot-password
# still creates the reset token (so the rest of the flow is testable),
# it just can't build a working link to put in the email, and skips
# sending one rather than emailing a broken link.
FRONTEND_URL = os.environ.get("FRONTEND_URL", "").rstrip("/")

# --- Startup -----------------------------------------------------------
database.init_db()

app = FastAPI(title="Loominous")


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


def similar_dreams_out(embedding, similar_dreams):
    """
    Turn find_similar's full dream dicts into the small collapsed-card
    shape the "Similar dreams" row actually needs (see SimilarDreamOut) --
    a match percentage against this dream's own embedding, plus a short
    snippet the frontend can expand to the full text on tap.
    """
    out = []
    for d in similar_dreams:
        score = engine.cosine_similarity(embedding, d["embedding"])
        text = d["raw_text"] or ""
        snippet = text if len(text) <= 70 else text[:67].rstrip() + "…"
        out.append({
            "id": d["id"],
            "timestamp": d["timestamp"],
            "match": round(max(0.0, min(1.0, score)) * 100),
            "snippet": snippet,
            "full": text,
        })
    return out


def _timed_stage(stage, rid, endpoint, fn, *args):
    with observability.timed("pipeline_stage", request_id=rid, endpoint=endpoint, stage=stage):
        return fn(*args)


def extract_and_embed(raw_text, rid, endpoint, emotions_reported=None):
    """
    extract_dream_data (a Claude call) and embed_text (a Voyage call)
    each only need raw_text -- nothing about one depends on the other's
    result -- so they used to just run back to back for no real reason,
    adding their two durations together into the total wait. Running
    them on separate threads overlaps those two waits instead, trimming
    a real, measurable slice off every /interpret and re-interpret call
    without changing what either one returns. (A plain thread pool is
    enough here, not asyncio -- this file's route handlers are sync, and
    both calls are blocking I/O the whole way down, which is exactly
    what threads are for.)

    emotions_reported passes straight through to extract_dream_data --
    embed_text has no use for it, it only needs the raw text.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        extract_future = pool.submit(_timed_stage, "extract", rid, endpoint, engine.extract_dream_data, raw_text, emotions_reported)
        embed_future = pool.submit(_timed_stage, "embed", rid, endpoint, engine.embed_text, raw_text)
        return extract_future.result(), embed_future.result()


# A control character, not a quote or a word -- essentially guaranteed to
# never show up in Claude's own prose or in JSON, so it's safe to use as
# the one marker that splits a streamed /interpret (or re-interpret)
# response into its two parts: the interpretation text itself (streamed
# as plain chunks, written straight to the page as it arrives) and, once
# that's done, a trailing JSON block carrying everything else the
# frontend needs (the dream's id, its extracted symbols/emotions/etc.,
# and the full interpretation text once more, for a final authoritative
# render). See stream_interpretation below.
STREAM_META_SEP = "\x1e"


def stream_interpretation(stream_fn, on_complete, log_endpoint, rid=None):
    """
    Shared by /interpret and the re-interpret path on PUT /dreams/{id}:
    both need to stream engine.interpret_dream_stream's text straight
    through to the client as it's generated (that's the one stage slow
    enough -- 6-14s, measured -- to actually be worth not making someone
    wait on), then once it's done, run whatever DB/vectorstore work that
    endpoint needs with the finished text (on_complete), then send the
    structured fields the frontend still needs behind STREAM_META_SEP.

    By the time this is called, request validation (bad input, auth) has
    already happened and raised a normal HTTPException
    if needed -- none of that can happen anymore once this starts, since
    the HTTP response (status 200) goes out as soon as the first chunk
    does. If interpret_dream_stream or on_complete fails partway through,
    there's no way left to change the status code, so the only option is
    to say so the same way everything else is said here: a trailing
    metadata block, just with an "error" field instead of the usual ones,
    which the frontend checks for before treating the response as done.
    """
    def generate():
        chunks = []
        try:
            with observability.timed("pipeline_stage", request_id=rid, endpoint=log_endpoint, stage="interpret"):
                for piece in stream_fn():
                    chunks.append(piece)
                    yield piece
            interpretation = "".join(chunks)
            meta = on_complete(interpretation)
            yield STREAM_META_SEP + json.dumps(meta)
        except Exception as exc:
            observability.log_event(
                "stream_error", request_id=rid, endpoint=log_endpoint,
                error=f"{type(exc).__name__}: {exc}",
            )
            yield STREAM_META_SEP + json.dumps({"error": str(exc) or "interpretation failed"})

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


def make_search_fn(user_id):
    """
    Build the search_dreams tool callback for engine.py's agentic tool
    loop (analyze_patterns, continue_conversation), scoped to one user.

    engine.py deliberately has no database or vectorstore access of its
    own (keeps it a pure AI layer, testable with no DB at all -- see
    tests/test_engine.py), so this closure is where a text query actually
    becomes dream records: embed it via Voyage, then reuse the same
    find_similar() every other similarity lookup in this file goes
    through, so the model's tool calls hit the identical Pinecone-or-
    in-memory path real dream creation does, never a third code path.
    """
    def search_fn(query, top_n=5):
        embedding = engine.embed_text(query, input_type="query")
        if not embedding:
            return []
        return find_similar(user_id, embedding, top_n=top_n)
    return search_fn


# --- Request / response shapes ------------------------------------------

class SignupIn(BaseModel):
    username: str
    password: str
    # Optional -- an account without one simply can't use "forgot
    # password" later, same as before this field existed. Also present
    # (and ignored) on login's payload, since both endpoints share this
    # model and login never reads it.
    email: str | None = None


class AuthOut(BaseModel):
    id: int
    username: str
    token: str


class ForgotPasswordIn(BaseModel):
    email: str


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str


class AccountOut(BaseModel):
    username: str
    email: str
    email_verified: bool


class DeleteAccountIn(BaseModel):
    password: str


class VerifyEmailIn(BaseModel):
    token: str


class ResendVerificationOut(BaseModel):
    sent: bool


class SetEmailIn(BaseModel):
    email: str


class DreamIn(BaseModel):
    raw_text: str
    # Optional 'YYYY-MM-DD' -- set when logging a dream from an earlier
    # night (several backfilled at once shouldn't all land on today),
    # left out to just use the current moment as always.
    date: str | None = None
    # Optional free-text place this dream was logged from (e.g.
    # "Istanbul") -- also entirely optional.
    location: str | None = None
    # Optional mood chips the person picked themselves at entry (see
    # #panel-log) -- compared later against "emotions", the AI's own read
    # of the text. Also entirely optional.
    emotions_reported: list[str] = []


class DreamDateIn(BaseModel):
    date: str  # 'YYYY-MM-DD'


class DreamDateOut(BaseModel):
    id: int
    timestamp: str


class DreamLocationIn(BaseModel):
    location: str  # free text; empty string clears it


class DreamLocationOut(BaseModel):
    id: int
    location: str


class DreamOut(BaseModel):
    id: int
    symbols: list[str]
    emotions: list[str]
    people: list[str]
    settings: list[str]
    themes: list[str]
    interpretation: str
    symbol_icons: dict[str, str] = {}


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
    location: str = ""
    symbol_icons: dict[str, str] = {}
    emotions_reported: list[str] = []
    # people/settings were always stored (see database._row_to_dream) and
    # already extracted on every dream, but this summary model never
    # passed them through, so the Journal's People/Places filter chips had
    # nothing to read. Additive only -- no schema or storage change, just
    # two existing fields now reaching the frontend.
    people: list[str] = []
    settings: list[str] = []
    # The AI's own emotional read, restricted to the same eight-word
    # Plutchik set emotions_reported is tagged from -- see
    # engine.extract_dream_data -- so the two can be compared in the
    # same vocabulary. "emotions" above stays free text, unrelated.
    emotions_plutchik: list[str] = []


class SimilarDreamOut(BaseModel):
    # What the "Similar dreams" row on a dream's own page needs -- not a
    # full DreamSummary, since it's shown as a small collapsed card
    # (match %, date, a short snippet) that only expands to the full text
    # on tap. See GET /dreams/{id}/similar.
    id: int
    timestamp: str
    match: int
    snippet: str
    full: str


class PatternsOut(BaseModel):
    count: int
    analysis: str
    # Each entry: {"date": "YYYY-MM-DD", "emotion": "Fear"} -- see the
    # /patterns handler for why this rides along and how it's used.
    emotion_sequence: list[dict] = []


class SymbolInsightIn(BaseModel):
    symbol: str
    # Stage 11.1: optional, defaults to "symbol" for every pre-existing
    # caller that never sent one. Stage 12: now also the category half of
    # the concept key (concept_key_for) used for occurrence lookup and
    # the interpretation cache row -- a person named Door and the symbol
    # Door never share a cache row or an occurrence set because of this.
    category: str = "symbol"


class SymbolInsightOut(BaseModel):
    teaser: str
    # Kept for backward compatibility: SymbolChatIn below sends this back
    # as prior context, so it keeps meaning the same thing it always has
    # -- the server sets it equal to "general" (see symbol_insight).
    meaning: str
    direction: str
    # Stage 11: the two-layer split shown in Element Detail. "general" is
    # Layer A ("Possible meanings" -- exploratory, not tied to this
    # person's specific dreams). "journal" is Layer B ("In your dreams"
    # -- grounded in their own records, or the fixed
    # JOURNAL_INSUFFICIENT_CONTEXT_MESSAGE when there isn't enough yet).
    general: str = ""
    journal: str = ""


class SymbolChatIn(BaseModel):
    symbol: str
    message: str
    # Stage 12: same role as SymbolInsightIn.category -- the category
    # half of the concept key this thread is stored and looked up under.
    category: str = "symbol"
    # The reflection this thread opens on -- the frontend already has it
    # on screen from /symbols/insight, so sending it back here means the
    # first message in a thread doesn't have to pay for a second,
    # redundant call to engine.symbol_insight just to re-derive context
    # the client already showed the person. Left blank, the server falls
    # back to generating it itself (e.g. a thread resumed from
    # somewhere that never had this text handy).
    meaning: str = ""
    direction: str = ""


class SymbolChatOut(BaseModel):
    reply: str
    conversation: list[dict]


class SymbolConversationOut(BaseModel):
    conversation: list[dict]


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
    birth_date: str = ""  # 'YYYY-MM-DD', optional -- replaces birth_year
    birthplace: str = ""
    current_location: str = ""
    gender: str = ""
    relationship_status: str = ""
    bio: str = ""
    picture: str = ""  # data: URI, resized/compressed client-side before it ever gets here


class ProfileOut(BaseModel):
    name: str
    birth_date: str
    birthplace: str
    current_location: str
    gender: str
    relationship_status: str
    bio: str
    picture: str


# --- Loom Map data foundation: personal meaning + connection feedback ------
# See database.py's init_db comment for why these are separate, purely
# user-authored tables rather than anything engine.py writes to.

class PersonalMeaningIn(BaseModel):
    subject_type: str  # 'symbol' | 'emotion' | 'person' | 'place'
    subject_label: str  # real-cased, as the person/UI knows it, e.g. "Water"
    subject_key: str = ""  # normalized lookup key; derived from subject_label when blank
    meaning: str
    note: str = ""


class PersonalMeaningOut(BaseModel):
    subject_type: str
    subject_key: str
    subject_label: str
    meaning: str
    note: str
    created_at: str
    updated_at: str


class ConnectionFeedbackIn(BaseModel):
    connection_key: str
    status: str  # 'relevant' | 'not_relevant' | 'confirmed' | 'dismissed'
    note: str = ""


class ConnectionFeedbackOut(BaseModel):
    connection_key: str
    status: str
    note: str
    created_at: str
    updated_at: str


# --- Accounts --------------------------------------------------------------

# A small blocklist of the most commonly breached/guessed passwords --
# not exhaustive (a real breached-password check, like the HaveIBeenPwned
# k-anonymity API, is out of scope here), just enough to catch the
# handful of passwords that would otherwise sail straight through the
# length-and-variety rule below while still being trivially guessable.
# Every one of these sits near the top of every public "most common
# passwords" list.
COMMON_WEAK_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789",
    "1234567890", "qwerty123", "qwertyuiop", "letmein123", "iloveyou1",
    "admin1234", "welcome123", "abc123456", "football1", "123123123",
    "11111111", "00000000", "changeme1", "trustno1", "dragon123",
}


def validate_password_strength(password):
    """
    Enforced on both signup and password reset -- "choosing a password"
    means the same thing either way, so both go through this one
    function rather than two copies of the same rules quietly drifting
    apart. Deliberately a floor, not a straitjacket: length plus a
    little real variety, not "must contain one of every character
    class," since composition rules like that are what push people
    toward predictable substitutions ("Password1!") rather than
    genuinely stronger passwords (this follows NIST 800-63B's guidance
    on the point). Raises HTTPException(400) naming exactly what's
    missing; index.html's own strength meter mirrors these same rules
    live as someone types, so this check is a backstop, not the first
    time they're hearing about it.
    """
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password should be at least 8 characters")
    if not any(c.isalpha() for c in password):
        raise HTTPException(status_code=400, detail="Password should include at least one letter")
    if not any(c.isdigit() for c in password):
        raise HTTPException(status_code=400, detail="Password should include at least one number")
    if password.lower() in COMMON_WEAK_PASSWORDS:
        raise HTTPException(status_code=400, detail="That password is too common -- please choose something less guessable")


@app.post("/signup", response_model=AuthOut)
def signup(payload: SignupIn, request: Request):
    # Capped per-IP so a script can't mass-create accounts -- 10/hour is
    # generous for an actual person signing up (even a mistyped password
    # or two) while making bulk account creation impractical.
    if not ratelimit.allow(f"signup:{ratelimit.client_ip(request)}", max_calls=10, window_seconds=3600):
        raise HTTPException(status_code=429, detail="Too many signup attempts -- please try again later")
    username = payload.username.strip()
    password = payload.password
    email = (payload.email or "").strip().lower()
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are both required")
    validate_password_strength(password)
    # Required, not optional -- an account with no email has no way to
    # use "forgot password" later, so every account needs one on file.
    # Deliberately a loose format check, not a real RFC 5322 validator,
    # just enough to catch an obvious typo before it becomes an address
    # nothing can ever actually reach.
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="That doesn't look like a valid email address")
    try:
        user = database.create_user(username, email, password)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    # No verification email here -- database.create_user() marks a
    # brand-new account verified immediately now, so user["verify_token"]
    # is always None at this point and this never fires. Left in place
    # (rather than removed) because it's still exactly correct for the
    # one case that can still reach it: a legacy account that predates
    # this change getting a fresh token issued some other way. Nothing
    # about this ever blocks signup itself either way.
    if user.get("verify_token") and FRONTEND_URL:
        verify_url = f"{FRONTEND_URL}/?verify={user['verify_token']}"
        emailer.send_verification_email(email, verify_url)
    return AuthOut(**user)


@app.post("/login", response_model=AuthOut)
def login(payload: SignupIn, request: Request):
    # Capped per-IP so a wrong password can't be brute-forced by just
    # retrying fast -- 15 attempts per 15 minutes is loose enough for a
    # person fumbling their own password a few times, tight enough that
    # guessing a real password this way isn't practical.
    if not ratelimit.allow(f"login:{ratelimit.client_ip(request)}", max_calls=15, window_seconds=900):
        raise HTTPException(status_code=429, detail="Too many login attempts -- please wait a few minutes and try again")
    # payload.username doubles as "username or email" here -- the field
    # name stayed the same (so the request shape doesn't change), but
    # authenticate_user now checks both columns itself.
    user = database.authenticate_user(payload.username.strip(), payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Wrong username or password")
    return AuthOut(**user)


# --- Forgot / reset password -------------------------------------------
# Standard email-a-link flow. The one rule that matters most here:
# /forgot-password's response must never let anyone tell the difference
# between "that email has an account" and "it doesn't" -- so it always
# returns the same {"ok": true}, whether or not a reset token actually
# got created, and whether or not sending even succeeded.

@app.post("/forgot-password")
def forgot_password(payload: ForgotPasswordIn, request: Request):
    # This is the one endpoint where "no rate limit" doesn't just enable
    # brute-forcing -- it lets a caller repeatedly email a *third party*
    # who never asked for it, at Resend's expense. Capped per-IP at
    # 5/hour: enough for someone who fat-fingered their own email once
    # or twice, nowhere near enough to run as a harassment or
    # quota-exhaustion tool. Still returns the same {"ok": true} either
    # way below (no reason for a 429 here to leak anything either), it
    # just stops actually creating a token or sending anything once the
    # limit's hit.
    if not ratelimit.allow(f"forgot:{ratelimit.client_ip(request)}", max_calls=5, window_seconds=3600):
        return {"ok": True}
    email = payload.email.strip().lower()
    if email:
        reset = database.create_password_reset_token(email)
        if reset and FRONTEND_URL:
            reset_url = f"{FRONTEND_URL}/?reset={reset['reset_token']}"
            emailer.send_password_reset_email(email, reset_url)
    return {"ok": True}


@app.post("/reset-password", response_model=AuthOut)
def reset_password(payload: ResetPasswordIn):
    validate_password_strength(payload.new_password)
    user = database.reset_password_with_token(payload.token, payload.new_password)
    if user is None:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired -- request a new one")
    return AuthOut(**user)


# --- Account status & email verification --------------------------------
# Legacy-only now: a brand-new signup is already verified (see
# database.create_user), so this GET /account check comes back clean for
# every new account and the frontend's reminder bar never shows. This
# machinery still exists, and still works exactly as before, for
# whatever account was already sitting unverified before that became the
# rule -- never a gate on using the app either way, only ever a nudge.

@app.get("/account", response_model=AccountOut)
def get_account(authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    return AccountOut(
        username=user["username"],
        email=user.get("email") or "",
        email_verified=bool(user.get("email_verified")),
    )


@app.delete("/account")
def delete_account(payload: DeleteAccountIn, authorization: str | None = Header(default=None)):
    """
    Permanently delete the calling account: every dream, the profile,
    the login itself -- gone, immediately. There's no undo and no grace
    period, so on top of the frontend's own "are you sure?" step, this
    also requires the account's current password in the request body --
    a valid bearer token alone (e.g. one left signed in on a shared
    computer, or lifted some other way) isn't enough to irreversibly
    erase the account, the same way most real apps gate "delete my
    account" behind re-entering a password rather than treating it like
    any other authenticated action.

    Rate-limited per account (not IP, same reasoning as
    resend-verification) -- otherwise this would just be a second,
    lower-profile login endpoint to brute-force a password against.

    Order: pull this user's dream ids and clear their vectors out of
    Pinecone *before* touching Turso, so a crash partway through leaves
    at worst a few orphaned vectors (harmless -- they just point at dream
    ids that no longer exist and nothing will ever query them again
    once the account's gone) rather than a Turso row deleted with no way
    to know which Pinecone vectors used to belong to it.
    """
    user = get_current_user(authorization)
    if not ratelimit.allow(f"delete-account:{user['id']}", max_calls=5, window_seconds=900):
        raise HTTPException(status_code=429, detail="Too many attempts -- please wait a few minutes and try again")
    if not database.verify_password(user["id"], payload.password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    dream_ids = database.get_dream_ids(user["id"])
    vectorstore.delete_user_dreams(user["id"], dream_ids)
    database.delete_account(user["id"])
    return {"deleted": True}


@app.post("/logout")
def logout(authorization: str | None = Header(default=None)):
    """
    Invalidate the calling token server-side. Logging out used to only
    be a frontend thing (clearSession() dropping the token from
    localStorage) -- the token itself stayed valid against every
    endpoint here until it naturally expired, up to TOKEN_LIFETIME (30
    days) later. That's the gap this closes: if a token was ever on a
    shared/public computer, or got copied out some other way, "log out"
    now actually revokes it rather than just hiding it from the browser
    that logged out, leaving it just as usable to whoever still has a
    copy. database.clear_token() already existed for exactly this (its
    own docstring has said "used by POST /logout" since before this
    route did) -- it just had no route calling it yet.
    """
    user = get_current_user(authorization)
    database.clear_token(user["id"])
    return {"logged_out": True}


@app.post("/verify-email")
def verify_email(payload: VerifyEmailIn):
    ok = database.verify_email_with_token(payload.token)
    if not ok:
        raise HTTPException(status_code=400, detail="This verification link is invalid or has expired")
    return {"verified": True}


@app.post("/account/email", response_model=ResendVerificationOut)
def set_account_email(payload: SetEmailIn, authorization: str | None = Header(default=None)):
    """
    Add (or change) the email on file for an already-logged-in account.
    This is the one path that matters most: an account created before
    email was required at signup has nothing on file for
    /forgot-password to send a link to, and no other way to get one
    short of this.

    Loose format check only, same reasoning as signup's. Rate-limited
    per account for the same reason as /resend-verification: this sends
    an email, so the thing to prevent is one account mashing it into a
    stream of mail to whatever address it names.
    """
    user = get_current_user(authorization)
    if not ratelimit.allow(f"set-email:{user['id']}", max_calls=5, window_seconds=3600):
        raise HTTPException(status_code=429, detail="Too many attempts -- please wait a few minutes and try again")
    email = payload.email.strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="That doesn't look like a valid email address")
    try:
        token = database.set_account_email(user["id"], email)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if token is None:
        raise HTTPException(status_code=404, detail="Account not found")
    sent = False
    if FRONTEND_URL:
        verify_url = f"{FRONTEND_URL}/?verify={token}"
        sent = bool(emailer.send_verification_email(email, verify_url))
    return ResendVerificationOut(sent=sent)


@app.post("/resend-verification", response_model=ResendVerificationOut)
def resend_verification(authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    # Keyed by account, not IP, since this one's already authenticated --
    # the thing to prevent is one logged-in account mashing this button
    # (or a script doing it for them) into an endless stream of emails to
    # itself, which an IP-based limit wouldn't even catch for someone on
    # a shared or rotating IP.
    if not ratelimit.allow(f"resend-verify:{user['id']}", max_calls=3, window_seconds=3600):
        return ResendVerificationOut(sent=False)
    token = database.create_email_verify_token(user["id"])
    if not token or not FRONTEND_URL:
        # Nothing to do (no email on file, already verified) or nowhere
        # to send a working link -- either way, not an error from the
        # person's side, just nothing happened.
        return ResendVerificationOut(sent=False)
    verify_url = f"{FRONTEND_URL}/?verify={token}"
    sent = emailer.send_verification_email(user.get("email") or "", verify_url)
    return ResendVerificationOut(sent=bool(sent))


# --- Logging a dream ------------------------------------------------------

# Every endpoint below this point that calls Claude or Voyage (a dream
# interpretation, a re-interpretation, a patterns pass, a symbol
# reflection, a follow-up reply) spends real money per call. A token is
# just a bearer secret like any other: if one ever leaked, or a buggy
# retry loop on the frontend (or anywhere else calling this API directly)
# got stuck resending, nothing here would have stopped it from running up
# unbounded API spend. These caps are sized generously for how someone actually
# uses this app -- logging dreams, asking follow-ups, checking patterns --
# not for scripted, continuous use; see each call site for its own
# reasoning. Keyed per-account (user id), not per-IP, since every one of
# these already requires a valid token -- the thing worth bounding is
# "how much can this one account cost," regardless of which network it's
# called from.

def require_ai_budget(kind, user_id, max_calls, window_seconds):
    if not ratelimit.allow(f"{kind}:{user_id}", max_calls=max_calls, window_seconds=window_seconds):
        raise HTTPException(
            status_code=429,
            detail="You're doing that a lot right now -- please wait a bit and try again.",
        )


@app.post("/interpret")
def interpret(dream: DreamIn, request: Request, authorization: str | None = Header(default=None)):
    """
    Streams back the interpretation as plain text, chunk by chunk, as
    Claude writes it -- not JSON. Once the text is done, one more chunk
    follows: STREAM_META_SEP (see its own docstring) plus a JSON object
    with this dream's id and everything else DreamOut used to carry in
    one shot. See stream_interpretation for the full shape, including
    what an error partway through looks like on the wire.
    """
    user = get_current_user(authorization)
    # 40/hour -- generous for even an unusually prolific night of
    # journaling (this is also hit by editing/re-interpreting, below),
    # nowhere near what a person typing dreams by hand would run into.
    require_ai_budget("interpret", user["id"], max_calls=40, window_seconds=3600)
    raw_text = dream.raw_text.strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="raw_text cannot be empty")

    timestamp = None
    if dream.date:
        try:
            timestamp = database.normalize_dream_date(dream.date)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    location = (dream.location or "").strip() or None
    emotions_reported = [e.strip() for e in (dream.emotions_reported or []) if e.strip()]
    # Computed once and reused for both the interpretation prompt and the
    # row that gets persisted, so "when this dream happened" (what the
    # model is told) and "when it's recorded as happening" (what's saved)
    # can never quietly drift apart by the few milliseconds between two
    # separate datetime.now() calls.
    final_timestamp = timestamp or datetime.now().isoformat()

    # Same pipeline as gui.py's on_interpret(), just called from a web
    # request instead of a button click -- scoped to this user's own
    # archive and profile, so the reading draws on their actual life
    # and their own past dreams, not anyone else's.
    #
    # Each stage is timed and logged separately (see observability.py) --
    # this is the thing Loominous couldn't answer before Phase 3: if a /interpret
    # call is slow, which of these four steps actually took the time?
    rid = getattr(request.state, "request_id", None)
    profile = database.get_profile(user["id"])

    # extract and embed both only need raw_text -- see extract_and_embed's
    # own docstring for why these run concurrently instead of one after
    # the other.
    extracted, embedding = extract_and_embed(raw_text, rid, "/interpret", emotions_reported)
    with observability.timed("pipeline_stage", request_id=rid, endpoint="/interpret", stage="find_similar"):
        similar = find_similar(user["id"], embedding, top_n=3)

    def on_complete(interpretation):
        with observability.timed("pipeline_stage", request_id=rid, endpoint="/interpret", stage="persist"):
            new_id = database.insert_dream(
                user["id"], raw_text, extracted, interpretation, embedding,
                timestamp=final_timestamp, location=location, emotions_reported=emotions_reported,
            )
            # Index this dream's embedding in the vector database too (a
            # no-op if Pinecone isn't configured) -- done after the Turso
            # insert so the vector's dream_id metadata always points at a
            # row that actually exists.
            vectorstore.upsert_dream(user["id"], new_id, embedding)
        return {
            "id": new_id,
            "symbols": extracted.get("symbols", []),
            "emotions": extracted.get("emotions", []),
            "people": extracted.get("people", []),
            "settings": extracted.get("settings", []),
            "themes": extracted.get("themes", []),
            "interpretation": interpretation,
            "symbol_icons": extracted.get("symbol_icons", {}),
            "emotions_reported": emotions_reported,
            "emotions_plutchik": extracted.get("emotions_plutchik", []),
            # similar was already computed above to ground the reading
            # itself -- reused here so the result screen can show the
            # "Similar dreams" row without a second request.
            "similar": similar_dreams_out(embedding, similar),
        }

    return stream_interpretation(
        stream_fn=lambda: engine.interpret_dream_stream(raw_text, extracted, similar, profile, location=location, dream_timestamp=final_timestamp, emotions_reported=emotions_reported),
        on_complete=on_complete,
        log_endpoint="/interpret",
        rid=rid,
    )


@app.put("/dreams/{dream_id}")
def edit_dream(dream_id: int, dream: DreamIn, authorization: str | None = Header(default=None)):
    """
    Edit an already-logged dream's text and re-run the full pipeline on
    it -- a fresh extraction and a fresh interpretation, grounded in the
    corrected/expanded text rather than the original. The follow-up
    conversation on this dream is cleared (it was grounded in the old
    text and old reading, see database.update_dream), and the
    similarity search excludes this dream itself, so it never shows up
    as "similar to" its own past self.

    Streamed the same way /interpret is -- see that route's docstring
    and stream_interpretation for the wire format.
    """
    user = get_current_user(authorization)
    # Shares /interpret's own budget -- same underlying pipeline (a fresh
    # Claude interpretation), same reason to cap it.
    require_ai_budget("interpret", user["id"], max_calls=40, window_seconds=3600)
    raw_text = dream.raw_text.strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="raw_text cannot be empty")

    existing = database.get_dream(user["id"], dream_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="No dream with that id")

    profile = database.get_profile(user["id"])
    # See extract_and_embed's docstring -- same "these two don't depend on
    # each other, so don't make them wait in line" fix as /interpret. The
    # original emotions_reported (editing text never retags the mood
    # chips) still gets to weigh in on the fresh extraction, same as it
    # did the first time this dream was logged.
    extracted, embedding = extract_and_embed(raw_text, None, "/dreams/{id} (edit)", existing.get("emotions_reported"))
    similar = find_similar(user["id"], embedding, exclude_dream_id=dream_id, top_n=3)

    def on_complete(interpretation):
        database.update_dream(user["id"], dream_id, raw_text, extracted, interpretation, embedding)
        # Overwrite this dream's vector with the new embedding -- same id,
        # so it replaces the old one rather than leaving a stale duplicate
        # behind in the index.
        vectorstore.upsert_dream(user["id"], dream_id, embedding)
        return {
            "id": dream_id,
            "symbols": extracted.get("symbols", []),
            "emotions": extracted.get("emotions", []),
            "people": extracted.get("people", []),
            "settings": extracted.get("settings", []),
            "themes": extracted.get("themes", []),
            "interpretation": interpretation,
            "symbol_icons": extracted.get("symbol_icons", {}),
            "emotions_plutchik": extracted.get("emotions_plutchik", []),
        }

    # The dream's own location and timestamp (if any) aren't something this
    # edit touches -- carry both through so re-interpreting the text
    # doesn't silently drop the place, or silently start reading the dream
    # as if it just happened "right now" when it was actually backdated.
    return stream_interpretation(
        stream_fn=lambda: engine.interpret_dream_stream(
            raw_text, extracted, similar, profile,
            location=existing.get("location"), dream_timestamp=existing.get("timestamp"),
            emotions_reported=existing.get("emotions_reported"),
        ),
        on_complete=on_complete,
        log_endpoint="/dreams/{id} (edit)",
    )


@app.put("/dreams/{dream_id}/date", response_model=DreamDateOut)
def edit_dream_date(dream_id: int, payload: DreamDateIn, authorization: str | None = Header(default=None)):
    """
    Re-date an already-logged dream -- for backfilling several real
    dreams in one sitting, each actually from a different earlier night,
    without them all landing on today. Only the timestamp moves; the
    dream's text, interpretation, and conversation are untouched (that's
    what PUT /dreams/{id} is for).
    """
    user = get_current_user(authorization)
    try:
        timestamp = database.normalize_dream_date(payload.date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    updated = database.update_dream_timestamp(user["id"], dream_id, timestamp)
    if not updated:
        raise HTTPException(status_code=404, detail="No dream with that id")
    return DreamDateOut(id=dream_id, timestamp=timestamp)


@app.put("/dreams/{dream_id}/location", response_model=DreamLocationOut)
def edit_dream_location(dream_id: int, payload: DreamLocationIn, authorization: str | None = Header(default=None)):
    """
    Set, change, or clear (empty string) where an already-logged dream was
    from -- same idea as PUT /dreams/{id}/date. Only the location moves;
    the dream's text, interpretation, timestamp, and conversation are
    untouched.
    """
    user = get_current_user(authorization)
    location = payload.location.strip()

    updated = database.update_dream_location(user["id"], dream_id, location)
    if not updated:
        raise HTTPException(status_code=404, detail="No dream with that id")
    return DreamLocationOut(id=dream_id, location=location)


@app.get("/dreams/{dream_id}/similar", response_model=list[SimilarDreamOut])
def get_dream_similar(dream_id: int, authorization: str | None = Header(default=None)):
    """
    Nearby dreams by meaning, not keyword -- reuses this dream's own
    embedding, already stored on the row from when it was first
    interpreted (see database.insert_dream), so this doesn't re-embed
    anything or call any AI model. Returns [] rather than 404 for a dream
    logged before real embeddings existed (nothing to compare against
    yet), since that's not actually an error from the frontend's point of
    view -- the "Similar dreams" row just has nothing to show.
    """
    user = get_current_user(authorization)
    dream = database.get_dream(user["id"], dream_id)
    if dream is None:
        raise HTTPException(status_code=404, detail="No dream with that id")
    if not dream["embedding"]:
        return []
    similar = find_similar(user["id"], dream["embedding"], exclude_dream_id=dream_id, top_n=3)
    return similar_dreams_out(dream["embedding"], similar)


@app.get("/dreams/{dream_id}/emotions")
def get_dream_emotions(dream_id: int, authorization: str | None = Header(default=None)):
    """
    Backfills "What it carried" for a dream logged before emotions_plutchik
    existed (see index.html's fetchAndRenderEmotions and
    engine.classify_emotions_plutchik): if the dream already has it
    stored, returns that directly, no new Claude call. Otherwise runs one
    small, cheap classification pass over what's already on the row (its
    own text plus the free-text "emotions" its original extraction
    found) and persists the result -- never re-running the full
    extraction or re-interpreting the dream, so its stored text and
    reading are untouched either way.
    """
    user = get_current_user(authorization)
    dream = database.get_dream(user["id"], dream_id)
    if dream is None:
        raise HTTPException(status_code=404, detail="No dream with that id")
    existing = dream.get("emotions_plutchik") or []
    if existing:
        return {"emotions_plutchik": existing}
    # Shares interpret's own budget bucket -- same underlying cost (one
    # Claude call), just a much smaller one.
    require_ai_budget("interpret", user["id"], max_calls=40, window_seconds=3600)
    plutchik = engine.classify_emotions_plutchik(dream["raw_text"], dream.get("emotions", []), dream.get("emotions_reported"))
    database.update_dream_emotions_plutchik(user["id"], dream_id, plutchik)
    return {"emotions_plutchik": plutchik}


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
            location=d.get("location", ""),
            symbol_icons=d.get("symbol_icons", {}),
            emotions_reported=d.get("emotions_reported", []),
            emotions_plutchik=d.get("emotions_plutchik", []),
            people=d.get("people", []),
            settings=d.get("settings", []),
        )
        for d in all_dreams
    ]


@app.get("/dreams/count")
def dream_count(authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    return {"count": database.count_dreams(user["id"])}


@app.get("/patterns")
def patterns(request: Request, authorization: str | None = Header(default=None)):
    """
    Streams the reflection's text as Claude writes it, same wire format
    as /interpret -- see stream_interpretation for the shape (the text
    itself, then STREAM_META_SEP plus a trailing PatternsOut-shaped JSON
    object: count, analysis (the full text once more), and
    emotion_sequence). This is the slowest single call in the app (a
    multi-turn, tool-calling pass over the whole archive, see
    engine.analyze_patterns_stream), so it's the one most worth not
    leaving someone staring at a spinner for the whole time.
    """
    user = get_current_user(authorization)
    # 20/hour -- this is the most expensive single call in the app (a
    # multi-tool agentic pass over the whole archive), and nobody
    # legitimately re-checks their own patterns that often; this is
    # purely a ceiling against a stuck refresh loop or similar.
    require_ai_budget("patterns", user["id"], max_calls=20, window_seconds=3600)
    profile = database.get_profile(user["id"])
    all_dreams = database.get_all_dreams(user["id"])
    rid = getattr(request.state, "request_id", None)

    # One dominant emotion per dream, oldest to newest, for the "Where
    # you've been moving" drift chart on the frontend -- the same
    # Plutchik vocabulary the per-dream wheel already uses, just this
    # dream's single strongest tag rather than the full merged weighting
    # (emotions_plutchik is already ordered most-to-least dominant; see
    # engine.extract_dream_data). Falls back to the person's own
    # self-reported mood for a dream that predates emotions_plutchik and
    # was never lazily backfilled; a dream with neither is left out
    # entirely rather than guessed at. The timestamp rides along so the
    # frontend can label its "earlier" and "lately" groups with the real
    # date range each one spans, instead of a vague "when you started"
    # -- the grouping itself stays by position (first slice / last
    # slice of however many dreams this is), never a fixed calendar
    # window, since logging is too irregular for "last 30 days" to
    # reliably land on enough dreams to average. All the actual geometry
    # (angles, colors, centroids) is computed client-side from this
    # plain list, same division of labor as the per-dream mandala.
    emotion_sequence = []
    for dream in all_dreams:
        dominant = (dream.get("emotions_plutchik") or dream.get("emotions_reported") or [None])[0]
        if dominant:
            emotion_sequence.append({"date": dream["timestamp"][:10], "emotion": dominant})

    def on_complete(analysis):
        return {"count": len(all_dreams), "analysis": analysis, "emotion_sequence": emotion_sequence}

    return stream_interpretation(
        stream_fn=lambda: engine.analyze_patterns_stream(all_dreams, profile, search_fn=make_search_fn(user["id"])),
        on_complete=on_complete,
        log_endpoint="/patterns",
        rid=rid,
    )


# How many of this symbol's past occurrences get handed to the model as
# grounding context -- recent ones, not every single time it's ever come
# up, so the prompt (and the cost of generating this) stays bounded no
# matter how large someone's archive gets.
SYMBOL_INSIGHT_MAX_OCCURRENCES = 5


def _category_field_values(dream, category):
    """Which of a dream's extracted-element lists are relevant grounding
    for one category. "symbol" also searches themes (abstract mentions
    never shown as their own card, but still real grounding -- unchanged
    from pre-Stage-12 _symbol_occurrences, which searched all fields
    unconditionally); an unrecognized category falls back to every field,
    so a client sending something unexpected still gets *a* result rather
    than none."""
    if category == "symbol":
        return list(dream["symbols"]) + list(dream["themes"])
    if category == "emotion":
        return list(dream["emotions"])
    if category == "person":
        return list(dream["people"])
    if category == "place":
        return list(dream["settings"])
    return (
        list(dream["symbols"]) + list(dream["themes"]) + list(dream["people"])
        + list(dream["settings"]) + list(dream["emotions"])
    )


def _concept_occurrences(user_id, category, concept_key):
    """
    Stage 12: this user's dreams containing an occurrence whose concept
    key (concept_key_for) equals concept_key -- i.e. every dream feeding
    the consolidated concept, not just the ones using its exact wording
    ("my brother" and "brother" both count toward "person:brother"). Most
    recent first, bounded to SYMBOL_INSIGHT_MAX_OCCURRENCES, trimmed to
    just {date, excerpt} -- the shape both engine.symbol_insight and
    engine.symbol_chat_reply expect as grounding. Shared by
    /symbols/insight and /symbols/chat so a concept that doesn't exist in
    the archive 404s the same way from either one.
    """
    all_dreams = database.get_all_dreams(user_id)
    matches = [
        d for d in all_dreams
        if any(v and concept_key_for(category, v) == concept_key for v in _category_field_values(d, category))
    ]
    # Most recent occurrences first -- if there are more than the cap,
    # the newest ones are the most relevant grounding for "what this
    # tends to mean for you lately."
    matches.sort(key=lambda d: d["timestamp"], reverse=True)
    return [
        {"date": d["timestamp"][:10], "excerpt": d["raw_text"][:220]}
        for d in matches[:SYMBOL_INSIGHT_MAX_OCCURRENCES]
    ]


def _occurrence_fingerprint(occurrences):
    """
    Stage 11.1: a stable hash of exactly the content handed to the model
    as grounding (each occurrence's date + its excerpt, in order) -- not
    just how many there are or the newest date. occurrence_count and
    latest_occurrence_date alone can't catch every relevant edit: fixing
    a typo in an existing dream's text, or re-extracting it so a
    different excerpt gets included, can leave both of those unchanged
    while what the model would actually read has changed. This hash
    changes whenever that content changes, so it's what
    database.element_interpretations' fingerprint column is compared
    against below. List order matters on purpose -- _symbol_occurrences'
    own most-recent-first ordering is itself part of what the model saw,
    so a date edit that reorders occurrences is a real change too.
    """
    raw = json.dumps(occurrences, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# Stage 11.1 Part 3: a Python mirror of index.html's conceptLabelFor, used
# ONLY to decide what the *general* (Layer A) reading should be framed
# around -- never for occurrence lookup, authorization, personal-meaning
# storage, or anything else that treats a person as an individual rather
# than a concept. Keep these rules in sync with conceptLabelFor's own --
# see that function's comment in index.html for the full rationale (every
# rule anchored to the FULL label so "brother-in-law"/"father figure"/
# "my brother's house"/"Mother Nature" all correctly fall through).
_CONCEPT_PERSON_RULES = [
    (re.compile(r"^(brother)$"), "Brother"),
    (re.compile(r"^(sister)$"), "Sister"),
    (re.compile(r"^(mom|mother|mommy)$"), "Mother"),
    (re.compile(r"^(dad|father|daddy)$"), "Father"),
    (re.compile(r"^(girlfriend)( [a-z]+)?$"), "Girlfriend"),
    (re.compile(r"^(boyfriend)( [a-z]+)?$"), "Boyfriend"),
    (re.compile(r"^(friend|best friend)$"), "Friend"),
]


def concept_label_for(category, raw_label):
    """The broader concept a person label maps to ("my brother" ->
    "Brother"), or raw_label unchanged for any other category, or any
    person label not confidently classified. Purely textual, purely for
    shaping the general-interpretation prompt -- see the module comment
    above."""
    if category != "person" or not raw_label:
        return raw_label
    normalized = re.sub(r"^my\s+", "", raw_label.strip().lower())
    for pattern, label in _CONCEPT_PERSON_RULES:
        if pattern.match(normalized):
            return label
    return raw_label


# Stage 12 Part 4/5: ONE CONCEPT, ONE NODE. Everything below is a Python
# mirror of index.html's conceptSlugFor/conceptDisplayLabelFor (same
# rules, kept in sync -- see that pair's own comment for the full
# rationale and the exclusion cases they're built to leave alone:
# brother-in-law, father figure, Mother Nature, girlfriend's sister,
# fear/anxiety, house/home, car/camper van, door/doorway). Unlike
# concept_label_for above (prompt-framing only), concept_key_for is now
# the actual identity used for occurrence lookup, interpretation-cache
# rows, and symbol-chat threads -- so two concepts with the same display
# text but different categories (a person named Door, a symbol Door)
# can never collide, and "my brother"/"brother" or "a door"/"door"
# resolve to the exact same concept.
_ARTICLE_RE = re.compile(r"^(a|an|the)\s+")


def concept_slug_for(category, raw_label):
    """Stable, lowercase, category-local identifier that differently-worded
    occurrences of the same symbolic concept collapse to. Only person and
    symbol categories have real alias rules right now (Part 5); emotion
    and place -- and any person/symbol label not confidently classified --
    fall through to the plain normalized (trim+lower) text, identical to
    pre-Stage-12 behavior, so nothing not explicitly listed in Part 5 ever
    gets merged."""
    if not raw_label:
        return ""
    normalized = raw_label.strip().lower()
    if category == "symbol":
        stripped = _ARTICLE_RE.sub("", normalized).strip()
        return stripped or normalized
    if category == "person":
        stripped = re.sub(r"^my\s+", "", normalized)
        for pattern, display in _CONCEPT_PERSON_RULES:
            if pattern.match(stripped):
                return display.lower()
        return normalized
    return normalized


def concept_key_for(category, raw_label):
    """Category-aware concept identifier, e.g. "person:brother" or
    "symbol:door" -- the one value used as the actual lookup/cache/thread
    key everywhere below, so a same-text-different-category pair can
    never collide."""
    return category + ":" + concept_slug_for(category, raw_label)


def concept_display_label_for(category, raw_label):
    """The text shown wherever a surface displays the symbolic concept
    itself (Map nodes, Element Detail header, related-dreams stat) --
    never a rewrite of the dream's own original wording, which stays in
    raw_text/people/symbols untouched (Part 15). Delegates to
    concept_label_for for person, falling back to a simple
    capitalization for an unmatched person label so cosmetic casing
    doesn't regress from pre-Stage-12 behavior; symbol gets the same
    leading-article strip as concept_slug_for, then capitalized."""
    if not raw_label:
        return raw_label
    if category == "person":
        mapped = concept_label_for(category, raw_label)
        if mapped != raw_label:
            return mapped
        s = raw_label.strip()
        return (s[0].upper() + s[1:]) if s else s
    if category == "symbol":
        s = raw_label.strip()
        stripped = _ARTICLE_RE.sub("", s) or s
        return (stripped[0].upper() + stripped[1:]) if stripped else stripped
    return raw_label


@app.post("/symbols/insight", response_model=SymbolInsightOut)
def symbol_insight(payload: SymbolInsightIn, authorization: str | None = Header(default=None)):
    """
    A short, personalized reflection on one symbol or theme -- grounded
    in this person's own dreams it actually appeared in.

    Stage 11 Part 11 ("do not trigger AI calls on every page render"):
    this reuses a cached reading (database.element_interpretations)
    whenever this user's occurrences for this symbol haven't actually
    changed since it was last generated. Stage 11.1: "changed" is judged
    by a content fingerprint (_occurrence_fingerprint), not just
    occurrence_count/latest_occurrence_date -- those two didn't catch an
    edit to an existing dream that left the count and the newest date
    the same. A real content change is the "explicit, controlled
    refresh" trigger; nothing else (opening the screen again, re-tapping
    the node) causes a fresh Claude call.

    Stage 12: occurrence lookup and the cache row itself are keyed by
    concept_key (category-prefixed, alias-aware -- see concept_key_for),
    not the literal symbol text, so "my brother"/"brother" share one
    cached reading and a person named Door can never collide with the
    symbol Door. A legacy row from before Stage 12 (keyed by the old
    literal lowercased label) is simply never looked up again under its
    old key -- it's left in place untouched, not deleted, and the first
    request for the now-consolidated concept generates and caches a new
    row under the concept key.
    """
    user = get_current_user(authorization)
    symbol = payload.symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol cannot be empty")
    category = payload.category or "symbol"
    concept_key = concept_key_for(category, symbol)
    concept_label = concept_display_label_for(category, symbol)

    occurrences = _concept_occurrences(user["id"], category, concept_key)
    if not occurrences:
        raise HTTPException(status_code=404, detail="That symbol wasn't found in your archive")

    occurrence_count = len(occurrences)
    latest_occurrence_date = occurrences[0]["date"]
    fingerprint = _occurrence_fingerprint(occurrences)

    cached = database.get_element_interpretation(user["id"], concept_key)
    # A legacy row (no fingerprint yet -- see init_db's migration) reads
    # back with occurrence_fingerprint == "", which can never equal a
    # real computed hash, so it's correctly treated as stale here and
    # regenerated once, lazily, the next time this one element happens
    # to be requested -- not a bulk pass over every cached row.
    if cached and cached.get("occurrence_fingerprint") and cached["occurrence_fingerprint"] == fingerprint:
        return SymbolInsightOut(
            teaser=cached["teaser"],
            meaning=cached["general_text"],
            direction=cached["direction"],
            general=cached["general_text"],
            journal=cached["journal_text"],
        )

    require_ai_budget("symbol-insight", user["id"], max_calls=40, window_seconds=3600)
    result = engine.symbol_insight(symbol, occurrences, concept_label=concept_label, category=category)
    teaser = result.get("teaser", "")
    general_text = result.get("general", "")
    journal_text = result.get("journal", "")
    direction = result.get("direction", "")

    database.save_element_interpretation(
        user["id"], concept_key, concept_label,
        teaser, general_text, journal_text, direction,
        occurrence_count, latest_occurrence_date, fingerprint,
    )

    return SymbolInsightOut(
        teaser=teaser,
        meaning=general_text,
        direction=direction,
        general=general_text,
        journal=journal_text,
    )


# --- Each symbol's own chat thread ------------------------------------------
# Separate from a dream's /continue chat on purpose: the same symbol often
# turns up across many dreams, so the conversation about it belongs to the
# symbol itself (keyed by (user, symbol_key) in symbol_chats), not to
# whichever single dream someone happened to tap into it from.

@app.get("/symbols/chat", response_model=SymbolConversationOut)
def get_symbol_chat(symbol: str, category: str = "symbol", authorization: str | None = Header(default=None)):
    """The conversation so far for one symbol's thread, or an empty one
    if it's never been opened. Stage 12: keyed by concept_key, same as
    /symbols/insight's cache -- a thread started under "my brother" and
    one opened later from the consolidated "Brother" concept are the
    same thread; a person and a symbol sharing the same display text
    never share one."""
    user = get_current_user(authorization)
    symbol = symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol cannot be empty")
    concept_key = concept_key_for(category or "symbol", symbol)
    conversation = database.get_symbol_conversation(user["id"], concept_key)
    return SymbolConversationOut(conversation=conversation)


@app.post("/symbols/chat", response_model=SymbolChatOut)
def symbol_chat(payload: SymbolChatIn, authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    # A back-and-forth thread naturally has more turns than a one-shot
    # insight, hence the higher ceiling than symbol-insight's.
    require_ai_budget("symbol-chat", user["id"], max_calls=80, window_seconds=3600)
    symbol = payload.symbol.strip()
    message = payload.message.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol cannot be empty")
    if not message:
        raise HTTPException(status_code=400, detail="message cannot be empty")
    category = payload.category or "symbol"
    concept_key = concept_key_for(category, symbol)
    concept_label = concept_display_label_for(category, symbol)

    occurrences = _concept_occurrences(user["id"], category, concept_key)
    if not occurrences:
        raise HTTPException(status_code=404, detail="That symbol wasn't found in your archive")

    opening_reflection = {"meaning": payload.meaning, "direction": payload.direction}
    if not opening_reflection["meaning"] and not opening_reflection["direction"]:
        opening_reflection = engine.symbol_insight(symbol, occurrences, concept_label=concept_label, category=category)

    conversation = database.get_symbol_conversation(user["id"], concept_key)
    profile = database.get_profile(user["id"])
    reply = engine.symbol_chat_reply(
        symbol, occurrences, opening_reflection, conversation, message, profile=profile,
    )

    conversation = conversation + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]
    database.update_symbol_conversation(user["id"], concept_key, concept_label, conversation)
    return SymbolChatOut(reply=reply, conversation=conversation)


# --- Continuing the conversation about one dream ---------------------------

@app.post("/dreams/{dream_id}/continue", response_model=ContinueOut)
def continue_dream(dream_id: int, payload: ContinueIn, request: Request, authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    # Same ceiling reasoning as symbol-chat's -- a real conversation
    # naturally has more turns than a one-shot call.
    require_ai_budget("continue", user["id"], max_calls=80, window_seconds=3600)
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
        reply = engine.continue_conversation(
            messages, profile=profile, related_dreams=related,
            search_fn=make_search_fn(user["id"]), dream_timestamp=dream.get("timestamp"),
        )

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

# A generous but not unlimited cap on the profile picture's data: URI --
# the frontend already resizes/compresses to a small square before this
# is ever sent (see onAvatarFileChosen in index.html), so a real photo
# from any real camera lands nowhere near this. This exists only to stop
# someone from posting an enormous string directly to the API and
# bloating the database row, not to police image quality.
MAX_PICTURE_DATA_URI_LENGTH = 400_000

@app.get("/profile", response_model=ProfileOut)
def read_profile(authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    profile = database.get_profile(user["id"])
    return ProfileOut(
        name=profile["name"],
        birth_date=profile["birth_date"],
        birthplace=profile["birthplace"],
        current_location=profile["current_location"],
        gender=profile["gender"],
        relationship_status=profile["relationship_status"],
        bio=profile["bio"],
        picture=profile["picture_data"],
    )


@app.post("/profile", response_model=ProfileOut)
def write_profile(profile: ProfileIn, authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    if len(profile.picture) > MAX_PICTURE_DATA_URI_LENGTH:
        raise HTTPException(status_code=400, detail="That image is too large -- try a smaller photo")
    data = profile.model_dump()
    data["picture_data"] = data.pop("picture")
    database.save_profile(user["id"], data)
    return read_profile(authorization)


# --- Personal meanings: "Your meaning" for a symbol/emotion/person/place,
# kept structurally apart from anything AI-generated (see the brief's
# Personal Meaning section, and PersonalMeaningIn/Out above) ----------------

VALID_SUBJECT_TYPES = {"symbol", "emotion", "person", "place"}


def _personal_meaning_out(row):
    return PersonalMeaningOut(
        subject_type=row["subject_type"],
        subject_key=row["subject_key"],
        subject_label=row["subject_label"],
        meaning=row["meaning"],
        note=row["note"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@app.get("/personal-meanings", response_model=list[PersonalMeaningOut])
def list_personal_meanings(authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    return [_personal_meaning_out(row) for row in database.list_personal_meanings(user["id"])]


@app.put("/personal-meanings", response_model=PersonalMeaningOut)
def save_personal_meaning(payload: PersonalMeaningIn, authorization: str | None = Header(default=None)):
    """
    Create or update the signed-in user's own meaning for one subject.
    Upsert by design (PUT, not POST) -- saving again for the same
    subject just edits it in place, same as the brief's "add/edit"
    action for this feature. Never called from anywhere in engine.py,
    so an AI call can never overwrite what gets saved here.
    """
    user = get_current_user(authorization)
    subject_type = payload.subject_type.strip().lower()
    if subject_type not in VALID_SUBJECT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="subject_type must be one of: " + ", ".join(sorted(VALID_SUBJECT_TYPES)),
        )
    label = payload.subject_label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="subject_label cannot be empty")
    meaning = payload.meaning.strip()
    if not meaning:
        raise HTTPException(status_code=400, detail="meaning cannot be empty")
    key = (payload.subject_key.strip() or label).lower()
    row = database.save_personal_meaning(user["id"], subject_type, key, label, meaning, payload.note.strip())
    return _personal_meaning_out(row)


@app.delete("/personal-meanings/{subject_type}/{subject_key}")
def delete_personal_meaning(subject_type: str, subject_key: str, authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    database.delete_personal_meaning(user["id"], subject_type.strip().lower(), subject_key.strip().lower())
    return {"ok": True}


# --- Connection feedback: "relevant" / "not relevant" / "confirmed" on a
# suggested Loom Map connection or a Discoveries card (see database.py's
# connection_feedback comment -- this records explicit user feedback but
# does not retrain or otherwise change engine.py's output) -----------------

VALID_FEEDBACK_STATUSES = {"relevant", "not_relevant", "confirmed", "dismissed"}


def _connection_feedback_out(row):
    return ConnectionFeedbackOut(
        connection_key=row["connection_key"],
        status=row["status"],
        note=row["note"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@app.get("/connections/feedback", response_model=list[ConnectionFeedbackOut])
def list_connection_feedback(authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    return [_connection_feedback_out(row) for row in database.list_connection_feedback(user["id"])]


@app.put("/connections/feedback", response_model=ConnectionFeedbackOut)
def save_connection_feedback(payload: ConnectionFeedbackIn, authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    key = payload.connection_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="connection_key cannot be empty")
    status = payload.status.strip().lower()
    if status not in VALID_FEEDBACK_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="status must be one of: " + ", ".join(sorted(VALID_FEEDBACK_STATUSES)),
        )
    row = database.save_connection_feedback(user["id"], key, status, payload.note.strip())
    return _connection_feedback_out(row)
