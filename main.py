"""
main.py -- Loom's FastAPI backend. The "front door" of the building.

This is the first room: POST /interpret. It takes raw dream text, runs it
through the same engine.py pipeline the desktop GUI already uses, saves
the result to loom.db, and hands back JSON. Nothing in engine.py or
database.py changes -- this file is purely the door and the corridor to
the rooms that already exist.

Run it with:
    uvicorn main:app --reload

Then open http://127.0.0.1:8000/docs in a browser -- FastAPI builds that
page for you automatically from this file, and you can test /interpret
there without writing any frontend code yet.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import database
import engine

# --- Startup -----------------------------------------------------------
# Same as gui.py's first line: make sure the dreams table exists.
database.init_db()

app = FastAPI(title="Loom")


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
    # outside this building needs to see those raw numbers.
    id: int
    timestamp: str
    raw_text: str
    symbols: list[str]
    emotions: list[str]
    themes: list[str]
    interpretation: str


class PatternsOut(BaseModel):
    count: int
    analysis: str


# --- The room itself ------------------------------------------------------

@app.post("/interpret", response_model=DreamOut)
def interpret(dream: DreamIn):
    raw_text = dream.raw_text.strip()
    if not raw_text:
        # HTTPException is how a FastAPI endpoint says "bad request" --
        # it becomes a proper HTTP 400 response, not a Python crash.
        raise HTTPException(status_code=400, detail="raw_text cannot be empty")

    # Same four-stage pipeline as gui.py's on_interpret(), just called
    # from a web request instead of a button click.
    extracted = engine.extract_dream_data(raw_text)
    embedding = engine.embed_text(raw_text)
    all_dreams = database.get_all_dreams()
    similar = engine.find_similar_dreams(embedding, all_dreams, top_n=3)
    interpretation = engine.interpret_dream(raw_text, extracted, similar)

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
    # room doesn't need its own special case for that.
    all_dreams = database.get_all_dreams()
    analysis = engine.analyze_patterns(all_dreams)
    return PatternsOut(count=len(all_dreams), analysis=analysis)
