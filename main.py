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
import json
import os
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


def extract_and_embed(raw_text, rid, endpoint):
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
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        extract_future = pool.submit(_timed_stage, "extract", rid, endpoint, engine.extract_dream_data, raw_text)
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


class SymbolInsightIn(BaseModel):
    symbol: str


class SymbolInsightOut(BaseModel):
    teaser: str
    meaning: str
    direction: str


class SymbolChatIn(BaseModel):
    symbol: str
    message: str
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
    extracted, embedding = extract_and_embed(raw_text, rid, "/interpret")
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
            # similar was already computed above to ground the reading
            # itself -- reused here so the result screen can show the
            # "Similar dreams" row without a second request.
            "similar": similar_dreams_out(embedding, similar),
        }

    return stream_interpretation(
        stream_fn=lambda: engine.interpret_dream_stream(raw_text, extracted, similar, profile, location=location, dream_timestamp=final_timestamp),
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
    # each other, so don't make them wait in line" fix as /interpret.
    extracted, embedding = extract_and_embed(raw_text, None, "/dreams/{id} (edit)")
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
        }

    # The dream's own location and timestamp (if any) aren't something this
    # edit touches -- carry both through so re-interpreting the text
    # doesn't silently drop the place, or silently start reading the dream
    # as if it just happened "right now" when it was actually backdated.
    return stream_interpretation(
        stream_fn=lambda: engine.interpret_dream_stream(
            raw_text, extracted, similar, profile,
            location=existing.get("location"), dream_timestamp=existing.get("timestamp"),
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
    # 20/hour -- this is the most expensive single call in the app (a
    # multi-tool agentic pass over the whole archive), and nobody
    # legitimately re-checks their own patterns that often; this is
    # purely a ceiling against a stuck refresh loop or similar.
    require_ai_budget("patterns", user["id"], max_calls=20, window_seconds=3600)
    profile = database.get_profile(user["id"])
    all_dreams = database.get_all_dreams(user["id"])
    analysis = engine.analyze_patterns(all_dreams, profile, search_fn=make_search_fn(user["id"]))
    return PatternsOut(count=len(all_dreams), analysis=analysis)


# How many of this symbol's past occurrences get handed to the model as
# grounding context -- recent ones, not every single time it's ever come
# up, so the prompt (and the cost of generating this) stays bounded no
# matter how large someone's archive gets.
SYMBOL_INSIGHT_MAX_OCCURRENCES = 5


def _symbol_occurrences(user_id, symbol_key):
    """
    This user's dreams whose symbols/themes contain symbol_key (the same
    normalized, lowercased form the frontend groups tags by), most recent
    first, bounded to SYMBOL_INSIGHT_MAX_OCCURRENCES and trimmed down to
    just {date, excerpt} -- the shape both engine.symbol_insight and
    engine.symbol_chat_reply expect as grounding. Shared by /symbols/insight
    and /symbols/chat so a symbol that doesn't exist in the archive 404s
    the same way from either one.
    """
    all_dreams = database.get_all_dreams(user_id)
    matches = [
        d for d in all_dreams
        if symbol_key in [s.lower() for s in d["symbols"]] or symbol_key in [t.lower() for t in d["themes"]]
    ]
    # Most recent occurrences first -- if there are more than the cap,
    # the newest ones are the most relevant grounding for "what this
    # tends to mean for you lately."
    matches.sort(key=lambda d: d["timestamp"], reverse=True)
    return [
        {"date": d["timestamp"][:10], "excerpt": d["raw_text"][:220]}
        for d in matches[:SYMBOL_INSIGHT_MAX_OCCURRENCES]
    ]


@app.post("/symbols/insight", response_model=SymbolInsightOut)
def symbol_insight(payload: SymbolInsightIn, authorization: str | None = Header(default=None)):
    """
    A short, personalized reflection on one symbol or theme -- grounded
    in this person's own dreams it actually appeared in, generated fresh
    each time rather than cached, same as every other reflection in this
    app (the chat continuation, the interpretation itself). Deliberately
    not a static dream-dictionary lookup (see engine.symbol_insight).
    """
    user = get_current_user(authorization)
    require_ai_budget("symbol-insight", user["id"], max_calls=40, window_seconds=3600)
    symbol = payload.symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol cannot be empty")
    symbol_key = symbol.lower()

    occurrences = _symbol_occurrences(user["id"], symbol_key)
    if not occurrences:
        raise HTTPException(status_code=404, detail="That symbol wasn't found in your archive")

    result = engine.symbol_insight(symbol, occurrences)
    return SymbolInsightOut(
        teaser=result.get("teaser", ""),
        meaning=result.get("meaning", ""),
        direction=result.get("direction", ""),
    )


# --- Each symbol's own chat thread ------------------------------------------
# Separate from a dream's /continue chat on purpose: the same symbol often
# turns up across many dreams, so the conversation about it belongs to the
# symbol itself (keyed by (user, symbol_key) in symbol_chats), not to
# whichever single dream someone happened to tap into it from.

@app.get("/symbols/chat", response_model=SymbolConversationOut)
def get_symbol_chat(symbol: str, authorization: str | None = Header(default=None)):
    """The conversation so far for one symbol's thread, or an empty one
    if it's never been opened."""
    user = get_current_user(authorization)
    symbol_key = symbol.strip().lower()
    if not symbol_key:
        raise HTTPException(status_code=400, detail="symbol cannot be empty")
    conversation = database.get_symbol_conversation(user["id"], symbol_key)
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
    symbol_key = symbol.lower()

    occurrences = _symbol_occurrences(user["id"], symbol_key)
    if not occurrences:
        raise HTTPException(status_code=404, detail="That symbol wasn't found in your archive")

    opening_reflection = {"meaning": payload.meaning, "direction": payload.direction}
    if not opening_reflection["meaning"] and not opening_reflection["direction"]:
        opening_reflection = engine.symbol_insight(symbol, occurrences)

    conversation = database.get_symbol_conversation(user["id"], symbol_key)
    profile = database.get_profile(user["id"])
    reply = engine.symbol_chat_reply(
        symbol, occurrences, opening_reflection, conversation, message, profile=profile,
    )

    conversation = conversation + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]
    database.update_symbol_conversation(user["id"], symbol_key, symbol, conversation)
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
