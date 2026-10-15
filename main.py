"""
main.py -- Loom's FastAPI backend. The "front door" of the building.

Rooms in this building:
  POST /signup, POST /login  -- create or access an account
  POST /interpret             -- log a new dream, get back its reading
  GET  /dreams                 -- your archive, oldest-first summaries
  GET  /dreams/count           -- just the count
  GET  /patterns               -- cross-archive reflection
  POST /dreams/{id}/continue   -- keep talking about one specific dream
  GET  /profile, POST /profile -- who you are, so readings can be
                                  grounded in your actual life rather
                                  than staying generic

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

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import database
import engine

# --- Startup -----------------------------------------------------------
database.init_db()

app = FastAPI(title="Loom")

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
def interpret(dream: DreamIn, authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
    raw_text = dream.raw_text.strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="raw_text cannot be empty")

    # Same pipeline as gui.py's on_interpret(), just called from a web
    # request instead of a button click -- scoped to this user's own
    # archive and profile, so the reading draws on their actual life
    # and their own past dreams, not anyone else's.
    profile = database.get_profile(user["id"])
    extracted = engine.extract_dream_data(raw_text)
    embedding = engine.embed_text(raw_text)
    all_dreams = database.get_all_dreams(user["id"])
    similar = engine.find_similar_dreams(embedding, all_dreams, top_n=3)
    interpretation = engine.interpret_dream(raw_text, extracted, similar, profile)

    new_id = database.insert_dream(user["id"], raw_text, extracted, interpretation, embedding)

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
    other_dreams = [d for d in database.get_all_dreams(user["id"]) if d["id"] != dream_id]
    similar = engine.find_similar_dreams(embedding, other_dreams, top_n=3)
    interpretation = engine.interpret_dream(raw_text, extracted, similar, profile)

    database.update_dream(user["id"], dream_id, raw_text, extracted, interpretation, embedding)

    return DreamOut(
        id=dream_id,
        symbols=extracted.get("symbols", []),
        emotions=extracted.get("emotions", []),
        people=extracted.get("people", []),
        settings=extracted.get("settings", []),
        themes=extracted.get("themes", []),
        interpretation=interpretation,
    )


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
def continue_dream(dream_id: int, payload: ContinueIn, authorization: str | None = Header(default=None)):
    user = get_current_user(authorization)
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

    reply = engine.continue_conversation(messages)

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
