# Roadmap

Planned and proposed work that hasn't been built yet. Distinct from `PROJECT.md`
(current goals/non-goals) and `ARCHITECTURE.md` (how the system works today).
Entries here are ideas or queued tasks, not settled scope.

## Feature ideas

### Yomitan dictionary integration

Let the user optionally include definitions from local Yomitan-format
dictionaries alongside the AI-generated `definition_ja`, rather than relying
solely on the LLM.

- Yomitan dictionaries are `.zip` archives of JSON (`index.json` plus `term_bank_N.json` files, each entry roughly `[term, reading, tags, rules, score, glossary, sequence, tags]`). Parsing happens locally; no network calls are made.
- Proposed approach: a `backend/yomitan.py` module that parses a directory of dictionary `.zip` files (path set via an env var) into an in-memory term-to-glossary index built once at backend startup. `/generate` would also look up the word in that index and return any matches alongside the LLM-generated fields; the review UI would show both side-by-side for the user to merge/edit before export.
- **Tradeoff:** an in-memory index is simplest to build first, but adds to
  startup time as more/larger dictionaries are added and doesn't persist
  across restarts. Indexing into the existing (currently unused) Postgres
  container instead would be faster and persistent, at the cost of building
  that ingestion path now rather than later.
- **Note:** this would reverse `PROJECT.md`'s current non-goal "No Yomitan export
  parsing or browser extension hooks". That line needs revisiting if this
  goes ahead. The scope here is parsing Yomitan's dictionary file format as a
  data source, not hooking into the Yomitan browser extension itself.

## Engineering tasks

- **Plain-text generation mode: done.** A second generation path
  (`backend/llm.py::generate_card_plain`), selected via a mode toggle on
  `/generate`/`/generate/batch` (`GenerateRequest.mode`/
  `BatchGenerateRequest.mode`, `backend/models.py`) rather than a separate
  endpoint. Motivated by README.md's Troubleshooting note that dropping
  `response_format` from an OpenRouter request is faster than structured
  output. Ended up asking for the same eight fields as plain labeled text
  lines (parsed back into a `CardDraft` server-side) rather than one
  freeform blob, so the existing per-field review form
  (`frontend/index.html`'s `#cardBox`) needed no changes- see `PROMPTS.md`'s
  "Plain-text generation prompt" section and change log, and
  `tests/test_llm.py`/`tests/test_main.py`.
- **Batch Postgres persistence, export parity, and duplicate-check: done.**
  The single-word flow was already fully wired to Postgres end to end-
  `/generate` does the duplicate check before spending an LLM call and
  persists the raw card before any edit; `/export` checks
  `get_latest_export()`, calls AnkiConnect's `addNote` or
  `updateNoteFields` accordingly, and records the result via
  `record_export()` (see `ARCHITECTURE.md`, `frontend/index.js`'s
  `currentWordId`). Batch now matches it on all three counts:
  - **Persistence/export parity:** `/generate/batch`'s route
    (`backend/main.py`) calls `insert_word`/`insert_card` for each
    successfully-generated `BatchCardResult` and sets that result's
    `word_id` (`backend/models.py`). `frontend/index.js`'s
    `buildCarouselCard()` threads that `word_id` into a closure-scoped
    `cardWordId`, included in that card's own Export payload, mirroring
    `currentWordId` in the single-word flow. A batch export can now be
    tracked/updated via `get_latest_export`/`record_export` exactly like a
    single-word export.
  - **Pre-generation duplicate-check:** `/generate/batch`'s route now
    calls `find_word_by_kanji`/`get_card` per word before deciding what to
    hand to `generate_cards_batch()`- a hit is reassembled into a
    `BatchCardResult` straight from Postgres (`duplicate: true`, `word_id`
    already set, no LLM call), a miss is generated fresh, and the response
    preserves the uploaded file's original word order either way. This
    deliberately took the passive auto-fill UX the single-word flow already
    uses (see `ARCHITECTURE.md`), not the heavier notify-then-choose design
    once floated for this- `generate_cards_batch()` (`backend/llm.py`)
    still never touches `db.py`, keeping the duplicate check in the route
    and that layering intact. Two identical words *within one uploaded
    file* are still not deduped against each other, only against Postgres-
    same as `parse_and_validate` already leaves unhandled, not a new gap.
  - `tests/test_main.py` covers persistence, the failed-word (no card, no
    persistence) case, and the duplicate-word case (no LLM call, no
    re-persistence, correct response order).
  - Still missing regardless of the above: a `tests/test_db.py` suite
    exercising `backend/db.py` directly against a real database.
- **UML diagrams:** Diagram the repo's structure and data flow to make the
  architecture easier to reason about at a glance. `diagrams/` (PlantUML
  `.puml` source, see `diagrams/README.md`) exists for this; no diagrams
  have been written yet.
