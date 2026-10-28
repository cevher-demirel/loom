# Loominous — Claude Code agent instructions

## Project
Loominous (repository: cevher-demirel/loom) is a dream journal with a Loom Map. Frontend is primarily a single `index.html`; backend uses FastAPI and Turso/SQLite. Render deploys the backend from `main`; GitHub Pages serves the frontend.

## Production safety — mandatory
- Never push, merge, commit, or open a pull request against `main` without explicit owner approval.
- Never deploy or change Render, GitHub Pages, Turso, production data, accounts, dreams, identity mappings, or production secrets.
- Do not run migrations, delete data, or make live API requests.
- Do not expose, print, or request API keys, credentials, or user data.
- Work on a named development branch only when a later workflow explicitly grants write access.
- Preserve existing accounts, dreams, corrections, and user data.

## Development conventions
- Prefer small, targeted changes that fit the current plain JavaScript and FastAPI architecture.
- Keep the Loom Map categories Symbols, Emotions, People, Places distinct.
- Verify any work with local tests; never substitute passing test claims for actual results.
- Avoid live Anthropic, Voyage, Pinecone, Turso, or Render calls during tests. Use mocks and test placeholders only.
- Report what was inspected or changed, test commands and results, remaining risks, and whether anything was pushed.

## Pilot workflow
The initial `Claude Pilot (manual, read-only)` workflow is intentionally read-only. It must inspect only repository code and summarize the current architecture and recommended next safe development step. Do not modify files or execute commands. Its purpose is to verify the API connection and measure a small task's cost before enabling coding automation.

## Future automation guardrails
Before adding write access, require a separate owner-reviewed workflow change, a protected development branch, bounded runtime and concurrency, and a human approval gate for PR merges. Never auto-merge or auto-deploy.
