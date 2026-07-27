# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local-only tool that generates Japanese Anki flashcards using a locally-hosted LLM (Ollama), with a review step before export to Anki via AnkiConnect. Strictly local/single-user by design — no cloud LLMs, no auth, no multi-user features (see `PROJECT.md` "Non-goals" for the full list before proposing features in those directions).

## Running it

```bash
docker compose up -d                                                            # starts Ollama + Postgres containers
docker exec -it ollama_japanese_llm ollama pull yuma/DeepSeek-R1-Distill-Qwen-Japanese:14b   # one-time model pull
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 5000                                   # from project root
```

Frontend (static HTML/JS prototype, not yet the Electron shell described in `ARCHITECTURE.md`):

```bash
cd frontend
python -m http.server 8080          # or open frontend/index.html directly via file://
```

Test the model directly, bypassing the backend entirely (useful for isolating whether a bad/slow card is a prompt or backend issue):

```bash
docker exec -it ollama_japanese_llm ollama run yuma/DeepSeek-R1-Distill-Qwen-Japanese:14b
```

`scripts/test_ollama.sh` has raw `curl` calls against Ollama's own REST API (port 11435) for the same kind of isolation testing, independent of both the backend and the `ollama` Python client.

There is no test suite and no lint/format command wired up yet — `black` is listed in `requirements.txt` but not invoked from anywhere in the repo.

## Configuration

Env vars (all optional, defaults are for local dev):

- `OLLAMA_HOST` — default `http://localhost:11435`. Note the port shift: `docker-compose.yml` maps the container's `11434` to host `11435`, so backend code and `docker exec` commands target different ports for the same service.
- `ANKICONNECT_URL` — default `http://localhost:8765`.
- `ANKI_DECK_NAME` / `ANKI_NOTE_TYPE` — default `Japanese` / `Basic`. `Basic` only has Front/Back fields; see the field-folding note below.
- `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` — defaults in `docker-compose.yml`, override via an uncommitted local `.env`.

## Architecture

Three pieces, talking over HTTP, no shared process:

```
frontend (static HTML/JS)  →  backend/main.py (FastAPI, port 5000)  →  Ollama container (port 11435)
                                                                    →  AnkiConnect (port 8765, talks to Anki desktop)
```

- `backend/llm.py` — requests **all six card fields in a single Ollama call**, using `CardDraft.model_json_schema()` (Pydantic → JSON Schema) passed as Ollama's `format` parameter to force structured output. There isn't a per-field or multi-call generation path; if you need to change what gets generated, this is the one call to change.
- `backend/models.py` — `CardDraft` (LLM output shape: `expression, reading, definition_ja, nuance, example_sentence, jlpt_level`) vs. `ExportRequest` (export-to-Anki shape: `expression, reading, definition, nuance, example, jlpt`). **The field names differ between the two** (`definition_ja` vs `definition`, `example_sentence` vs `example`, `jlpt_level` vs `jlpt`) — `frontend/index.js` is what bridges the two shapes today (reads `data.definition_ja` into a `definition` form field, then posts `definition` back on export). Keep this in mind when touching any of `models.py`, `main.py`, `anki.py`, or `index.js` — a rename on one side silently breaks the other unless all four are updated together.
- `backend/anki.py` — folds all six card fields down into just `Front`/`Back` HTML (`_build_fields`), because the default `Basic` Anki note type only has two fields. This is a deliberate stopgap, not a bug — a custom note type with all six fields is the intended eventual setup (see README "Configuration").
- `backend/db.py` — currently empty. `DATABASE.md` documents an intended Postgres schema (`words` / `cards` tables, chosen over SQLite specifically to avoid file/volume-sharing issues across containers) and the `postgres` service already runs via `docker-compose.yml`, but nothing in `backend/` connects to it yet.
- CORS in `backend/main.py` is wide open (`allow_origins=["*"]`) intentionally, since the frontend is served from a different origin (`file://` or `:8080`) than the API and this is a local single-user tool with no auth — not something to tighten as a "fix" without a reason tied to an actual change in that assumption.
- The model (`yuma/DeepSeek-R1-Distill-Qwen-Japanese:14b`) is a distilled *reasoning* model — it emits chain-of-thought before its structured answer, measured at roughly 2 tokens/sec on modest hardware, so a single card generation can take several minutes. Relevant to any change touching request timeouts or frontend loading states.
- Batch `.txt` upload is designed (`PROJECT.md`) but not implemented — single-word generation only exists today, in both `backend/main.py`'s `/generate` endpoint and `frontend/index.js`.

## Docs map

- `PROJECT.md` — goals, non-goals, target users, error-handling UX copy
- `ARCHITECTURE.md` — intended full pipeline (Electron shell, not yet built)
- `PROMPTS.md` — the actual prompt template and model choice rationale
- `DATABASE.md` — intended schema (ahead of current `backend/db.py` implementation)
- `README.md` — setup/run instructions
