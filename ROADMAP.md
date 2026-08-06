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

- **Batch Postgres persistence & export parity (next up):** the single-word
  flow is fully wired to Postgres end to end- `/generate` does the duplicate
  check before spending an LLM call and persists the raw card before any
  edit; `/export` checks `get_latest_export()`, calls AnkiConnect's
  `addNote` or `updateNoteFields` accordingly, and records the result via
  `record_export()` (see `ARCHITECTURE.md`, `frontend/index.js`'s
  `currentWordId`). Batch isn't- `generate_cards_batch()` (`backend/llm.py`)
  and `BatchCardResult` (`backend/models.py`) never touch Postgres at all,
  so batch-generated cards have no `word_id`, and a batch `/export` call
  always falls back to a plain `addNote` with nothing recorded (see
  `ExportRequest`'s optional `word_id` in `backend/models.py`- that's the
  field that's currently always absent for a batch card). To close the gap:
  - Add `word_id: int | None` to `BatchCardResult`.
  - Persist each successfully-generated batch word to Postgres
    (`insert_word`/`insert_card`, mirroring `/generate`'s route) and set
    that result's `word_id`. **Open design question to resolve when picking
    this up:** should that persistence live inside `generate_cards_batch()`
    itself (`backend/llm.py`), or move up into `/generate/batch`'s route
    (`backend/main.py`), matching where `/generate`'s own duplicate-check +
    persistence currently lives? The latter keeps `llm.py` free of any
    `db.py` dependency (today's layering), at the cost of restructuring how
    `generate_cards_batch()` hands results back to the route.
  - Thread `result.word_id` through `frontend/index.js`'s
    `buildCarouselCard()`- each carousel card needs its own captured
    word_id (mirroring `currentWordId` in the single-word flow), included
    in that card's own Export button payload.
  - Update `tests/test_llm.py`/`tests/test_main.py` for whichever module
    ends up owning the new DB calls.
  - Separate, larger decision, don't conflate with the above: whether batch
    should also get the *pre-generation* duplicate check (skip the LLM call
    per already-seen word, notify, sequential cancel/fetch-and-edit prompts-
    the original fuller design discussed earlier in the project) is bigger
    UX scope than just giving batch cards a `word_id`, and worth deciding
    explicitly rather than assuming it's included.
  - Still also missing regardless of the above: a `tests/test_db.py` suite
    exercising `backend/db.py` directly against a real database.
- **UML diagrams:** Diagram the repo's structure and data flow to make the
  architecture easier to reason about at a glance. `diagrams/` (PlantUML
  `.puml` source, see `diagrams/README.md`) exists for this; no diagrams
  have been written yet.
