# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What this is

A single-user tool that generates Japanese Anki flashcards using the free-tier OpenRouter cloud LLM API, with a review step before export to Anki via AnkiConnect. No auth, no multi-user features (see `PROJECT.md` "Non-goals" for the full list before proposing features in those directions).

## Running it

```bash
docker compose up -d                                                            # starts the Postgres container
# Set OPENROUTER_API_KEY in your environment (or an uncommitted local .env) before generating cards
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 5000 --env-file .env                   # from project root; --env-file is required for .env vars to actually load
```

Frontend (static HTML/JS, run directly in a browser):

```bash
cd frontend
python -m http.server 8080          # or open frontend/index.html directly via file://
```

There is no lint/format command wired up yet. `black` is listed in `requirements.txt` but not invoked from anywhere in the repo. A `pytest` suite does exist under `tests/`; run it with `pytest` from the project root.

## Configuration

Env vars (all optional except `OPENROUTER_API_KEY`, defaults are for local dev):

- `OPENROUTER_API_KEY`: required for `/generate` to work; no default, and `backend/llm.py` raises a clear `LLMError` if unset rather than failing obscurely.
- `OPENROUTER_MODELS`: comma-separated candidate models, default is a few free-tier models (see `backend/llm.py::DEFAULT_MODELS`).
- `ANKICONNECT_URL`: default `http://localhost:8765`.
- `ANKI_DECK_NAME` / `ANKI_NOTE_TYPE`: default `Japanese` / `Basic`. `Basic` only has Front/Back fields; see the field-folding note below.
- `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`: defaults in `docker-compose.yml`, override via an uncommitted local `.env`.

## Architecture

Three pieces, talking over HTTP, no shared process:

```text
frontend (static HTML/JS)  →  backend/main.py (FastAPI, port 5000)  →  OpenRouter API (cloud, via requests)
                                                                    →  AnkiConnect (port 8765, talks to Anki desktop)
```

- `backend/llm.py`: requests **all eight card fields in a single OpenRouter call**, posting directly to `https://openrouter.ai/api/v1/chat/completions` via `requests` and passing `CardDraft.model_json_schema()` as a `response_format: json_schema` payload to force structured JSON output. Retries once if the response's `expression` doesn't contain the requested word (cloud models can still drift onto an unrelated word, same as the local model this replaced; see `PROMPTS.md` change log). There isn't a per-field or multi-call generation path; if you need to change what gets generated, this is the one call to change.
- OpenRouter is the sole LLM provider (see `PROMPTS.md` change log for the prior Gemini/Ollama history). `OPENROUTER_MODELS` is a comma-separated list of candidates, sent as OpenRouter's native `models` array so OpenRouter itself falls back to the next entry if one is rate-limited or pulled from the free tier, rather than the backend needing its own retry loop.
- `backend/models.py`: `CardDraft` (LLM output shape: `expression, reading, definition_ja, nuance, synonyms, antonyms, example_sentence, jlpt_level`) vs. `ExportRequest` (export-to-Anki shape: `expression, reading, definition, nuance, synonyms, antonyms, example, jlpt`). **Most field names differ between the two** (`definition_ja` vs `definition`, `example_sentence` vs `example`, `jlpt_level` vs `jlpt`)- `synonyms`/`antonyms` are the exception, named identically on both sides since there's no qualifier to strip. `frontend/index.js` is what bridges the two shapes today (reads `data.definition_ja` into a `definition` form field, then posts `definition` back on export). Keep this in mind when touching any of `models.py`, `main.py`, `anki.py`, or `index.js`: a rename on one side silently breaks the other unless all four are updated together.
- `backend/anki.py`: folds all eight card fields down into just `Front`/`Back` HTML (`_build_fields`), because the default `Basic` Anki note type only has two fields. This is a deliberate stopgap, not a bug. A custom note type with all eight fields is the intended eventual setup (see README "Configuration"). Confirmed working end-to-end (real `addNote` call reaching a running Anki instance via AnkiConnect, card appears in the deck)- that confirmation predates the `synonyms`/`antonyms` addition, though, so it hasn't been re-verified against the current eight-field shape yet.
- `backend/db.py`: SQLAlchemy engine/session setup plus the ORM models and access functions for the schema `DATABASE.md` documents (`Word`, `Card`, `Export`; `init_db`, `insert_word`, `insert_card`, `find_word_by_kanji`, `get_card`, `get_latest_export`, `record_export`). `Card` rows are write-once for their generated content (inserted before the user edits anything- see `ARCHITECTURE.md`); `record_export()` does flip `Card.exported` to `True` afterwards, so it's the content columns that never change post-insert, not literally every column. `Export` is an append-only history of AnkiConnect calls, used to decide `addNote` vs `updateNoteFields` on a re-export. `init_db()` is called automatically on startup via a FastAPI `lifespan` hook in `backend/main.py`, so no manual step is needed after the Postgres container is up. Wired into **both** the single-word and batch flows for persistence, duplicate-checking, and export tracking: `/generate` calls `find_word_by_kanji`/`get_card`/`insert_word`/`insert_card`; `/generate/batch` does the same per word- calling `find_word_by_kanji`/`get_card` before generating, returning a `duplicate=True` result straight from Postgres on a hit, and only calling `insert_word`/`insert_card` for genuinely new words (see `BatchCardResult` in `backend/models.py`); `/export` calls `get_latest_export`/`record_export` whenever the request carries a `word_id`, single-word or batch alike (see `ExportRequest` in `backend/models.py`, `currentWordId` in `frontend/index.js`, and `cardWordId` in `buildCarouselCard()`). No `tests/test_db.py` yet exercising this module directly against a real database.
- CORS in `backend/main.py` is wide open (`allow_origins=["*"]`) intentionally, since the frontend is served from a different origin (`file://` or `:8080`) than the API and this is a local single-user tool with no auth. This isn't something to tighten as a "fix" without a reason tied to an actual change in that assumption.
- Batch `.txt` upload: `backend/batch.py::parse_and_validate` enforces the format (one word per line, kanji/hiragana/katakana only, max `MAX_WORDS = 12`) and raises `BatchValidationError` for the whole file on any violation. That's a single 400 response, not per-line. `POST /generate/batch` then calls `llm.generate_cards_batch`, which loops `generate_card` per word and catches `LLMError` per word (skip-and-continue) rather than failing the whole batch. Each word's result carries either `card` or `error` in `BatchCardResult`. The route checks each word against Postgres via `find_word_by_kanji` before generating (see the `backend/db.py` note above), then persists every newly-generated result (`insert_word`/`insert_card`, mirroring `/generate`) and sets that result's `word_id`. `frontend/index.js` renders one carousel card per result (`.carousel` / `.carousel-card`, horizontally scrollable); each successful card gets its own independent Discard/Export controls, same as the single-word flow, including its own `word_id` threaded into that card's Export payload. There's no bulk export.
- Verified end-to-end against a real OpenRouter response for the current eight-field `CardDraft` shape, including `synonyms`/`antonyms` (see `PROMPTS.md` change log's 2026-08-07 entry). Generation is slow but does complete, and the `response_format: json_schema` structured-output path has been observed working with a live API key. OpenRouter occasionally returns malformed JSON for a given attempt (surfaces as a normal `LLMError`)- regenerating the same word has been enough to recover in testing so far, so this isn't being treated as a bug to fix yet.

## Docs map

- `PROJECT.md`: goals, non-goals, target users, error-handling UX copy.
- `ARCHITECTURE.md`: full pipeline (browser-based frontend).
- `PROMPTS.md`: the actual prompt template and model choice rationale.
- `DATABASE.md`: schema (`words`/`cards`/`exports`) implemented in `backend/db.py` and wired into `backend/main.py`'s `/generate`, `/generate/batch`, and `/export` routes (see the `backend/db.py` bullet above).
- `README.md`: setup/run instructions.
- `diagrams/`: PlantUML (`.puml`) source files diagramming architecture and workflows, maintained alongside the `.md` docs (see `diagrams/README.md` for conventions).
