"""
main.py -- Loom's FastAPI backend. The "front door" of the building.

Rooms in this building:
  POST /signup, POST /login  -- create or access an account (login
                                 accepts a username or an email)
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
  POST /guest                  -- start trying it out with no account yet
  POST /claim-guest-dreams      -- fold a guest session's dreams into the
                                   account just signed up or logged into
  POST /interpret             -- log a new dream, get back its reading
  GET  /dreams                 -- your archive, oldest-first summaries
  PUT  /dreams/{id}             -- edit a dream's text, re-interpret it
  PUT  /dreams/{id}/date        -- backdate a dream to an earlier night
  PUT  /dreams/{id}/location    -- set/clear where a dream was from
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

import os
import secrets
import time
from datetime import datetime

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
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


class ClaimGuestIn(BaseModel):
    guest_token: str


class ClaimGuestOut(BaseModel):
    claimed: int


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


class AdminDeleteTestAccountIn(BaseModel):
    username: str


@app.post("/admin/delete-test-account")
def admin_delete_test_account(
    payload: AdminDeleteTestAccountIn,
    x_cleanup_secret: str | None = Header(default=None, alias="X-Cleanup-Secret"),
):
    """
    TEMPORARY maintenance endpoint, not part of the product -- deletes one
    disposable "uitest_*" account left over from manually testing in a
    browser. Double-gated so it can't be turned into a way to delete a
    real person's account even if the secret leaked: it needs the
    CLEANUP_SECRET env var to match X-Cleanup-Secret, *and* the username
    has to start with "uitest_". Meant to be removed (along with the
    CLEANUP_SECRET env var) once the current round of test accounts is
    cleaned up.
    """
    secret = os.environ.get("CLEANUP_SECRET")
    if not secret or not x_cleanup_secret or not secrets.compare_digest(x_cleanup_secret, secret):
        raise HTTPException(status_code=404)
    if not payload.username.startswith("uitest_"):
        raise HTTPException(status_code=400, detail="refusing to delete a non-test account")
    user_id = database.get_user_id_by_username(payload.username)
    if user_id is None:
        return {"deleted": False, "reason": "not found"}
    dream_ids = database.get_dream_ids(user_id)
    vectorstore.delete_user_dreams(user_id, dream_ids)
    database.delete_account(user_id)
    return {"deleted": True}


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
    email was required at signup -- or a guest who skipped it -- has
    nothing on file for /forgot-password to send a link to, and no
    other way to get one short of this.

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


# --- Trying it out before committing to an account --------------------------
# "Low-cost first entry": someone can land on Loom, type a dream, and see
# its interpretation before they've created anything. Under the hood this
# still makes a real account row (see create_guest_user) with a real
# token -- every other endpoint in this file works on it completely
# unchanged, it's just flagged is_guest so claim_guest_dreams() knows it's
# safe to fold its dreams into whatever account the person authenticates
# into next, and safe to throw away afterward.

@app.post("/guest", response_model=AuthOut)
def start_guest():
    user = database.create_guest_user()
    return AuthOut(**user)


@app.post("/claim-guest-dreams", response_model=ClaimGuestOut)
def claim_guest_dreams(payload: ClaimGuestIn, authorization: str | None = Header(default=None)):
    """
    Called right after a guest signs up or logs in for real (either one --
    whichever account they end up authenticated as gets the dream), to
    fold whatever they logged as a guest into that account. The caller's
    own token (the new, real one) says who to move the dreams *to*;
    `guest_token` -- the old one, which the frontend is about to discard
    -- says where to move them *from*. See claim_guest_dreams() in
    database.py for the actual security boundary (it only ever pulls
    from a genuine guest row, never a real account).
    """
    user = get_current_user(authorization)
    moved = database.claim_guest_dreams(payload.guest_token, user["id"])
    return ClaimGuestOut(claimed=moved or 0)


# --- Logging a dream ------------------------------------------------------

# A guest (see start_guest() above) can interpret this many dreams before
# being asked to create a real account -- enough to genuinely feel the
# product out, not so many that there's no reason left to sign up. Real
# accounts (is_guest=False) are never capped. Enforced here rather than
# only in the frontend, since a guest token is just as capable of calling
# this endpoint directly.
GUEST_DREAM_LIMIT = 3


@app.post("/interpret", response_model=DreamOut)
def interpret(dream: DreamIn, request: Request, authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    raw_text = dream.raw_text.strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="raw_text cannot be empty")

    if user.get("is_guest") and len(database.get_dream_ids(user["id"])) >= GUEST_DREAM_LIMIT:
        raise HTTPException(
            status_code=403,
            detail="You've used your 3 free dream interpretations -- create an account to keep logging and build your archive.",
        )

    timestamp = None
    if dream.date:
        try:
            timestamp = database.normalize_dream_date(dream.date)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    location = (dream.location or "").strip() or None
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
        interpretation = engine.interpret_dream(raw_text, extracted, similar, profile, location=location, dream_timestamp=final_timestamp)

    with observability.timed("pipeline_stage", request_id=rid, endpoint="/interpret", stage="persist"):
        new_id = database.insert_dream(user["id"], raw_text, extracted, interpretation, embedding, timestamp=final_timestamp, location=location)
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
    # The dream's own location and timestamp (if any) aren't something this
    # edit touches -- carry both through so re-interpreting the text
    # doesn't silently drop the place, or silently start reading the dream
    # as if it just happened "right now" when it was actually backdated.
    interpretation = engine.interpret_dream(
        raw_text, extracted, similar, profile,
        location=existing.get("location"), dream_timestamp=existing.get("timestamp"),
    )

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
    analysis = engine.analyze_patterns(all_dreams, profile, search_fn=make_search_fn(user["id"]))
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
