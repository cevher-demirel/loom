# Loom

A dream journal that doesn't just record dreams -- it reads them.

Log a dream in plain language and Loom extracts its symbols, emotions,
people, settings, and themes, then writes a grounded interpretation
drawing on cross-cultural dream symbolism, modern dream science (the
continuity hypothesis, threat simulation theory), and loosely-applied
Jungian archetypes -- never mystical claims, never literal predictions.
Every reading can be refined through conversation, and an optional
profile (who you are, what's going on in your life) lets interpretations
go deeper than generic pattern-matching.

**Live demo:** https://loom-phas.onrender.com/docs
*(Free-tier hosting, so the first request after a while may take ~20-30s
to wake up.)*

---

## What it does

- **Log a dream** -- describe it in your own words. Claude extracts
  structured data (symbols, emotions, people, settings, themes) and
  writes a 3-5 paragraph interpretation grounded in what was actually
  described, not horoscope-style generalities.
- **Find connections** -- each new dream is compared against your
  archive for recurring symbols and themes, so the interpretation can
  note genuine patterns rather than treating every dream as a one-off.
- **Keep talking about one dream** -- push back, add context Claude
  didn't have ("that house was actually my childhood home"), or ask to
  go deeper. Each reply remembers everything said about that specific
  dream.
- **Reflect across the whole archive** -- once you've logged a few
  dreams, ask for a cross-archive read on recurring symbols and
  emotional trajectory over time.
- **A profile that grounds everything** -- an optional "About You"
  section (name, age, background, what's going on in your life) that
  quietly informs every interpretation and pattern analysis, so "I was
  flying" lands differently for someone who just started a new job
  versus someone who just retired.
- **Two ways in** -- a desktop GUI (`gui.py`, built with CustomTkinter)
  for local use, and a web API + browser frontend for anywhere else.

## Architecture

```
gui.py ─────┐
            ├──▶ engine.py ──▶ Claude API (extraction, interpretation,
main.py ────┘                  conversation, pattern analysis)
  │
  └──▶ database.py ──▶ loom.db (SQLite)

loom.html ──(fetch)──▶ main.py (FastAPI, deployed on Render)
```

- **`engine.py`** -- the AI layer. Four jobs, deliberately kept separate:
  extraction, a lightweight "embedding" (word-overlap fingerprinting,
  explained below), interpretation, and cross-archive pattern analysis.
- **`database.py`** -- SQLite persistence for dreams, their extracted
  data, conversation threads, and the user's profile.
- **`main.py`** -- the FastAPI backend. Wraps the same pipeline
  `gui.py` uses in HTTP endpoints, so the desktop app and the web
  frontend share identical logic rather than duplicating it.
- **`gui.py`** -- a native desktop app (CustomTkinter) for local use,
  calling `engine.py`/`database.py` directly.
- **`loom.html`** -- a single self-contained static page (no build
  step, no framework) that talks to the deployed API over `fetch`.

## A deliberate engineering trade-off

The first version used `sentence-transformers` for real semantic
embeddings, to find dreams that were *thematically* similar even when
worded completely differently. It worked well locally -- and then
crashed immediately on Render's free tier with an out-of-memory error,
because `sentence-transformers` pulls in `torch`, which alone can use
500MB+ of RAM just sitting idle. The free tier gives 512MB total.

Rather than pay for a bigger instance to run a personal project, I
replaced the embedding step with a lightweight keyword-overlap
comparison (`engine.py`'s `embed_text`/`cosine_similarity`): each dream
is reduced to the set of its meaningful words, and similarity is scored
by Jaccard overlap between two dreams' word sets. It's less semantically
nuanced than a real embedding model -- it won't catch two dreams that
mean the same thing in totally different words -- but it reliably
catches recurring symbols, people, and settings, costs nothing to run,
and fits comfortably in the memory budget. A reasonable trade for a
personal archive, a bad one for a product with real similarity-search
requirements -- worth knowing the difference.

## Tech stack

- **Backend:** Python, FastAPI, SQLite
- **AI:** Claude API (Anthropic) -- `claude-sonnet-5-5` for extraction,
  interpretation, conversation, and pattern analysis
- **Desktop GUI:** CustomTkinter
- **Frontend:** vanilla HTML/CSS/JS, no build tooling
- **Hosting:** Render (free tier)

## Running it locally

```bash
git clone https://github.com/tovdemirel-glitch/loom.git
cd loom
pip install -r requirements.txt
```

Create a `.env` file with your Anthropic API key:

```
ANTHROPIC_API_KEY=your-key-here
```

**Desktop app:**
```bash
python gui.py
```

**Web backend:**
```bash
uvicorn main:app --reload
```
Then open `http://127.0.0.1:8000/docs` for interactive API docs, or open
`loom.html` directly in a browser (update the `API_BASE` constant near
the top of its `<script>` if you're not using the deployed URL).

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/interpret` | Log a dream, get back its reading |
| `GET` | `/dreams` | The archive, oldest-first |
| `GET` | `/dreams/count` | Just the count |
| `GET` | `/patterns` | Cross-archive reflection |
| `POST` | `/dreams/{id}/continue` | Keep talking about one dream |
| `GET`/`POST` | `/profile` | Read or save the "About You" context |

## What I'd do differently with more time

- Real semantic embeddings via a hosted API (e.g. Voyage AI) instead of
  the keyword-overlap stand-in, if the memory budget allowed for a
  dependency on another paid service.
- Auth, if this were ever more than a single-user personal tool.
- A proper frontend framework once the UI outgrows one HTML file.
