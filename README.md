# Loom

A dream reflection platform. Describe a dream, get a grounded interpretation
drawing on cross-cultural symbolism and real dream science (never religious,
never fortune-telling), and watch connections form across your dreams as
your archive grows.

## How it's built (the pipeline)

1. **Extraction** -- `engine.extract_dream_data()` turns your free-text
   description into structured data: symbols, emotions, people, settings,
   themes.
2. **Embedding** -- `engine.embed_text()` turns the dream into a numeric
   vector capturing its *meaning*, using a small local model
   (sentence-transformers), so similar dreams can be found even if they
   use completely different words.
3. **Retrieval** -- `engine.find_similar_dreams()` searches your archive
   for past dreams that are thematically close to the new one.
4. **Interpretation** -- `engine.interpret_dream()` generates the actual
   reflective reading, grounded in symbolism and dream science, optionally
   referencing similar past dreams.
5. **Storage** -- `database.py` saves everything permanently to a local
   SQLite file (`loom.db`), so your archive persists between sessions.
6. **Pattern analysis** -- `engine.analyze_patterns()` looks across your
   *entire* archive (not just one dream) to reflect on recurring themes
   and the apparent direction of your inner life over time.
7. **Conversation** -- after the first interpretation, the "Log a Dream"
   tab switches into follow-up mode: whatever you type next continues
   the dialogue about *that* dream (`engine.continue_conversation()`),
   instead of being treated as a brand-new entry. Click "New Dream" to
   deliberately start fresh. The full exchange is saved to that dream's
   row in the database as it grows. The Patterns tab works the same way.
8. **My Dreams** -- browse every dream you've logged individually; click
   one to reopen its full interpretation and conversation thread.
9. **Profile** -- a picture (auto-cropped circular), name, birth year,
   birthplace, current location, and a free-text bio about your life.
   This gets woven into both the interpretation and pattern-analysis
   prompts (`engine._profile_context()`), so readings can draw on your
   real context -- a career transition, a move, whatever's actually
   true -- rather than staying generic.

## Setup

1. Make sure you're in this project's folder with its virtual environment
   active (same pattern as your other projects):
   ```
   python -m venv venv
   venv\Scripts\activate
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
   Note: `sentence-transformers` will download a small model (~90MB) the
   first time it's used -- this needs an internet connection once, then
   it's cached locally and works offline after that.

3. Create a `.env` file in this folder with your Anthropic key:
   ```
   ANTHROPIC_API_KEY=sk-ant-api03-your-real-key-here
   ```
   (Same key you already use in your other projects.)

4. Run it:
   ```
   python gui.py
   ```

## What's genuinely new here, concept-wise

- **Structured extraction**: asking an LLM to return clean JSON instead
  of prose, and parsing it safely.
- **Real database**: SQLite instead of a flat log file -- supports real
  queries as the archive grows.
- **Embeddings & semantic similarity**: the core idea behind every real
  RAG system -- turning text into vectors so "similar meaning" can be
  found even without matching words.
- **Longitudinal analysis**: reasoning across many records at once,
  rather than a single exchange.
- **Pipeline architecture**: extraction, embedding, retrieval, and
  interpretation are kept as separate, single-purpose functions rather
  than one tangled block -- this is how real production AI systems are
  structured.

## Honest limitations (things to improve together)

- Pattern analysis sends the *entire* archive's extracted data into one
  prompt -- fine for dozens of dreams, but would need real chunking or
  summarization at hundreds+.
- The embedding model runs locally and is general-purpose, not
  dream-specific -- good enough to start, but there's room to tune this.
- No edit/delete of past entries yet.
- No "dream date" separate from "date logged" -- useful if you ever want
  to log a dream the morning after rather than typing it live.
