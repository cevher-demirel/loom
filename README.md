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
- **Accounts** -- username/password signup, with every dream,
  conversation, and profile scoped to its owner. One person can never
  read, edit, or delete another's archive.

## Architecture

```
gui.py ─────┐
            ├──▶ engine.py ──▶ Claude API (extraction, interpretation,
main.py ────┤                  conversation, pattern analysis)
  │         │               ╲
  │         │                ╲▶ Voyage AI (real semantic embeddings)
  │         │
  │         └──▶ vectorstore.py ──▶ Pinecone (similarity search)
  │
  └──▶ database.py ──▶ Turso (prod) or local SQLite (dev)

index.html ──(fetch)──▶ main.py (FastAPI, deployed on Render)
```

- **`engine.py`** -- the AI layer. Four jobs, deliberately kept separate:
  extraction, embedding (via Voyage AI, see below), interpretation, and
  cross-archive pattern analysis. Every Claude/Voyage call is logged
  through `observability.py` with stage name, duration, and token usage.
- **`vectorstore.py`** -- a thin client around Pinecone for storing and
  querying dream embeddings; a no-op (falls back to in-memory cosine
  similarity in `engine.py`) if `PINECONE_API_KEY` isn't set, so the app
  degrades gracefully without it rather than breaking.
- **`database.py`** -- persistence for dreams, their extracted data,
  conversation threads, accounts, and each user's profile. Two
  interchangeable backends: Turso (hosted, SQLite-compatible) in
  production, since Render's free tier wipes local disk on every
  redeploy; a local SQLite file for development.
- **`observability.py`** -- structured JSON logging and per-stage
  latency tracing for every Claude/Voyage call and HTTP request, plus
  the data behind `/health`.
- **`main.py`** -- the FastAPI backend. Wraps the same pipeline
  `gui.py` uses in HTTP endpoints, so the desktop app and the web
  frontend share identical logic rather than duplicating it.
- **`gui.py`** -- a native desktop app (CustomTkinter) for local use,
  calling `engine.py`/`database.py` directly.
- **`index.html`** -- a single self-contained static page (no build
  step, no framework) that talks to the deployed API over `fetch`.
- **`evals/`** -- an offline eval harness (fixed fixtures, rubric
  checks, LLM-as-judge) for grading interpretation *quality* -- a
  different concern from the correctness tests below, and one that
  needs a real Claude call to grade, so it's run manually rather than
  in CI.
- **`tests/`** -- a 51-test suite (unit tests for the pure logic in
  `engine.py` and `database.py`'s ownership isolation, plus
  integration tests against every endpoint with Claude/Voyage mocked
  out) run on every push and PR via GitHub Actions.

## An engineering trade-off, and how it got resolved

The first version used `sentence-transformers` for real semantic
embeddings, to find dreams that were *thematically* similar even when
worded completely differently. It worked well locally -- and then
crashed immediately on Render's free tier with an out-of-memory error,
because `sentence-transformers` pulls in `torch`, which alone can use
500MB+ of RAM just sitting idle. The free tier gives 512MB total.

Rather than pay for a bigger instance to run a personal project, that
version replaced the embedding step with a lightweight keyword-overlap
comparison: each dream reduced to its meaningful words, scored by
Jaccard overlap. It worked, but it couldn't catch two dreams that meant
the same thing in different words.

The real fix was swapping local inference for a hosted embedding API
(Voyage AI) -- no model weights loaded into the app's own memory at
all, so the free-tier memory ceiling stopped being a constraint. Dream
embeddings are now real semantic vectors, stored and queried through
Pinecone for similarity search, with a graceful in-memory fallback if
Pinecone isn't configured.

## Tech stack

- **Backend:** Python, FastAPI
- **Database:** Turso (hosted SQLite) in production, local SQLite file
  in development
- **AI:** Claude API (Anthropic) -- `claude-sonnet-5-5` for extraction,
  interpretation, conversation, and pattern analysis; Voyage AI
  (`voyage-3.5-lite`) for embeddings
- **Vector search:** Pinecone
- **Observability:** structured JSON logging + per-stage latency
  tracing (`observability.py`), `/health` endpoint
- **Testing/CI:** pytest (51 tests) via GitHub Actions on every push/PR
- **Desktop GUI:** CustomTkinter
- **Frontend:** vanilla HTML/CSS/JS, no build tooling
- **Hosting:** Render (free tier)

## Running it locally

```bash
git clone https://github.com/cevher-demirel/loom.git
cd loom
pip install -r requirements.txt
```

Create a `.env` file:

```
ANTHROPIC_API_KEY=your-key-here
VOYAGE_API_KEY=your-key-here

# Optional -- omit any of these and that piece degrades gracefully
# (local SQLite instead of Turso, no Pinecone-backed similarity search)
TURSO_DATABASE_URL=
TURSO_AUTH_TOKEN=
PINECONE_API_KEY=
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
`index.html` directly in a browser (update the `API_BASE` constant near
the top of its `<script>` if you're not using the deployed URL).

**Running the test suite:**
```bash
pip install -r requirements-dev.txt
pytest
```

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/signup` | Create an account |
| `POST` | `/login` | Get an auth token |
| `POST` | `/interpret` | Log a dream, get back its reading |
| `PUT` | `/dreams/{id}` | Edit a dream's text, re-interpret it |
| `DELETE` | `/dreams/{id}` | Remove a dream from the archive |
| `GET` | `/dreams` | The archive, oldest-first |
| `GET` | `/dreams/count` | Just the count |
| `GET` | `/patterns` | Cross-archive reflection |
| `POST` | `/dreams/{id}/continue` | Keep talking about one dream |
| `PUT` | `/dreams/{id}/conversation` | Edit/delete a message in that thread |
| `GET`/`POST` | `/profile` | Read or save the "About You" context |
| `GET` | `/health` | Liveness + dependency status |

## What I'd do differently with more time

- A proper frontend framework once the UI outgrows one HTML file.
- Rate limiting per account -- right now a single user could hammer
  `/interpret` and run up the Claude/Voyage bill.
- Password reset flow -- signup/login exist, but there's no recovery
  path if someone forgets their password.
