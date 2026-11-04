# Stage 24d — Brother-style reflection failures

## What the owner saw
Element page: "Couldn't put together a reflection on this right now" with empty *Possible meanings* / *In your dreams*
headings above it; after **Try again**, "Thinking about it…" again.

## Investigation (code audit; production logs were not available)
| Hypothesis | Finding |
|---|---|
| Auth / 401 | `authedFetch` already retries 401 and signs out cleanly; the error box is suppressed for `unauthorized`. Not the cause. |
| Name normalisation | `concept_key_for("person","Brother")` = `person:brother` on both paths; occurrences found (12). Not the cause. |
| Response parsing | Frontend wire parser is tolerant; backend parser is intentionally **strict** (all 5 markers in order, non-empty general/direction). A reading cut off before `END` is rejected → the "error" meta. Output budget was 1536 tokens for up to 5 grounding excerpts: plausible truncation. |
| Provider timeout / hang | `client.messages.stream` had **no per-request timeout** (SDK default 10 min) and the browser had **no stall detection**: a stalled provider call leaves "Thinking about it…" indefinitely. Confirmed gap. |
| Concurrency | Retry already cancels the previous stream and disables the button; no server-side duplicate suppression (cache is only written after a complete, valid reading). |
| Caching | Success is cached by occurrence fingerprint (server) and in memory (browser); failures are never cached. Correct. |
| Error exposure | The stream sent `str(exc)` to the browser; the UI filtered it, but internals still crossed the wire. |

The exact trigger of the owner's failure cannot be proven without server logs; the confirmed defects are the missing
timeout/stall handling, strict parse of a possibly-truncated stream with no fallback, raw exception text on the wire,
and a UI that showed empty section headings and an indefinite spinner.

## Changes
* **State model** (`symbolReflectionState`): idle · loading · success · empty · recoverable · nonrecoverable. The journal
  facts (counts, "What the journal shows") are local and stay visible in every state.
* **Loading** is one `role="status"` line; empty section headings are hidden until they have text.
* **Failure** is `role="alert"`, fixed friendly text, **Try again** (44px) — hidden only for "not in your journal anymore".
* **Stall watchdog** (45 s without a chunk, aborts the request) → recoverable failure "taking longer than expected".
* **One bounded fallback**: an unexplained stream failure triggers one request to the non-streaming endpoint; not for
  sign-out, not-found, the rate-limit notice, stalls or aborts. No automatic loop; retry is always a person's tap.
* **Duplicates**: retry ignored while loading; a new attempt aborts the old one; leaving the screen aborts and invalidates.
* **Late failure never overwrites a success**; a revisit reuses the cached reading (no AI call).
* **Backend**: per-request timeout 75 s, `max_tokens` 2048, and the stream's failure message is one fixed sentence (detail
  stays in the server log). Stage 21's submission request id is not used here.
