"""
main.py -- Loom's FastAPI backend. The "front door" of the building.

Rooms in this building:
  POST /interpret           -- log a new dream, get back its reading
  GET  /dreams               -- the archive, oldest-first summaries
  GET  /dreams/count         -- just the count
  GET  /patterns             -- cross-archive reflection
  POST /dreams/{id}/continue -- keep talking about one specific dream
  GET  /profile, POST /profile -- who you are, so readings can be grounded
                                  in your actual life rather than staying
                                  generic

Nothing in engine.py or database.py changes its own logic here -- this
file is purely the door and the corridors to rooms that already exist.

Run it with:
    uvicorn main:app --reload

Then open http://127.0.0.1:8000/docs in a browser -- FastAPI builds that
page for you automatically from this file, and you can test any of these
endpoints there without writing any frontend code.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import database
import engine

# --- Startup -----------------------------------------------------------
# Same as gui.py's first line: make sure the dreams table exists.
database.init_db()

app = FastAPI(title="Loom")

# --- CORS ----------------------------------------------------------------
# The frontend (loom.html) is a separate static file that may be opened
# straight from disk or hosted somewhere else entirely, not served by
# this app. Without this, a browser calling /interpret or /dreams from
# that page would be silently blocked by the browser's same-origin
# policy. allow_origins=["*"] is fine here -- this is a personal
# portfolio project with no cookies or auth tokens to protect.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request / response shapes ------------------------------------------
# Pydantic models are FastAPI's way of saying "a request to this door must
# look like this, or it gets turned away before your code even runs."
# This is the type-safety net that replaces manually checking `if raw_text`
# in the GUI code.

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
    # What the archive list sends back -- no embedding vector, nobody
    # outside this building needs to see those raw numbers. It DOES
    # include the conversation, so the frontend can render each dream's
    # existing follow-up chat without a second request per dream.
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


# --- The room itself ------------------------------------------------------

@app.post("/interpret", response_model=DreamOut)
def interpret(dream: DreamIn):
    raw_text = dream.raw_text.strip()
    if not raw_text:
        # HTTPException is how a FastAPI endpoint says "bad request" --
        # it becomes a proper HTTP 400 response, not a Python crash.
        raise HTTPException(status_code=400, detail="raw_text cannot be empty")

    # Same pipeline as gui.py's on_interpret(), just called from a web
    # request instead of a button click -- now also grounded in whatever
    # profile context has been saved, so the reading can draw on the
    # person's actual life rather than staying generic.
    profile = database.get_profile()
    extracted = engine.extract_dream_data(raw_text)
    embedding = engine.embed_text(raw_text)
    all_dreams = database.get_all_dreams()
    similar = engine.find_similar_dreams(embedding, all_dreams, top_n=3)
    interpretation = engine.interpret_dream(raw_text, extracted, similar, profile)

    new_id = database.insert_dream(raw_text, extracted, interpretation, embedding)

    return DreamOut(
        id=new_id,
        symbols=extracted.get("symbols", []),
        emotions=extracted.get("emotions", []),
        people=extracted.get("people", []),
        settings=extracted.get("settings", []),
        themes=extracted.get("themes", []),
        interpretation=interpretation,
    )


# --- Reading the archive ---------------------------------------------------
# Two more rooms, both read-only: the list view and the cross-archive
# reflection. Same corridor pattern as /interpret -- call straight into
# database.py / engine.py, reshape what comes back, hand it out the door.

@app.get("/dreams", response_model=list[DreamSummary])
def list_dreams():
    all_dreams = database.get_all_dreams()
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
def dream_count():
    return {"count": database.count_dreams()}


@app.get("/patterns", response_model=PatternsOut)
def patterns():
    # Same call gui.py's on_analyze() makes -- analyze_patterns() already
    # handles the "fewer than 3 dreams" case honestly on its own, so this
    # room doesn't need its own special case for that. Also grounded in
    # profile context now, same reasoning as /interpret above.
    profile = database.get_profile()
    all_dreams = database.get_all_dreams()
    analysis = engine.analyze_patterns(all_dreams, profile)
    return PatternsOut(count=len(all_dreams), analysis=analysis)


# --- Continuing the conversation about one dream ---------------------------
# This is what lets a reading refine itself: rather than the interpretation
# being a one-shot verdict, the person can push back, add context Claude
# didn't have ("that house was actually my childhood home" / "I've been
# going through a divorce"), or just ask to go deeper -- and each reply
# builds on everything said so far about THIS dream specifically.

@app.post("/dreams/{dream_id}/continue", response_model=ContinueOut)
def continue_dream(dream_id: int, payload: ContinueIn):
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    dream = database.get_dream(dream_id)
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
    database.update_dream_conversation(dream_id, conversation)

    return ContinueOut(reply=reply, conversation=conversation)


# --- Profile: who you are -----------------------------------------------
# A small, persistent bit of context -- not tied to any one dream -- that
# every interpretation and pattern analysis can draw on. Filling this in
# is what lets "I was flying" land differently for someone who just
# started a new job versus someone who just retired.

@app.get("/profile", response_model=ProfileOut)
def get_profile():
    profile = database.get_profile()
    return ProfileOut(
        name=profile["name"],
        birth_year=profile["birth_year"],
        birthplace=profile["birthplace"],
        current_location=profile["current_location"],
        bio=profile["bio"],
    )


@app.post("/profile", response_model=ProfileOut)
def save_profile(profile: ProfileIn):
    database.save_profile(profile.model_dump())
    return get_profile()
