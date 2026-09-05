# Anki Tool v2

[![CI](https://github.com/h3l333/anki-card-generator/actions/workflows/ci.yml/badge.svg)](https://github.com/h3l333/anki-card-generator/actions/workflows/ci.yml)

Generate Japanese Anki flashcards using the OpenRouter API (free-tier LLM access).

## Prerequisites

- Docker/Docker Compose (for the Postgres container).
- Python 3.x.
- An OpenRouter API key (free tier available).
- Anki (with AnkiConnect, if using that export path).

## Setup

1. `docker compose up -d` (starts the Postgres container).
2. Set `OPENROUTER_API_KEY` as an environment variable (or in `.env`); see Configuration.
3. Install Python deps: `pip install -r requirements.txt`.

Then see "Usage" below - `python scripts/dev.py` starts everything (Postgres, backend, frontend) in one command.

## Usage

Recommended: `python scripts/dev.py` from the project root starts Postgres, the backend, and the frontend together, then open `http://localhost:8080`. Stop with Ctrl+C (the Postgres container keeps running per its `restart: unless-stopped` policy in `docker-compose.yml` - run `docker compose down` if you want to stop it too).

The steps below are what that script runs, spelled out individually - useful if you want to run just one piece or see what's happening under the hood:

1. Start the database container: `docker compose up -d`.
2. Start the backend: `uvicorn backend.main:app --reload --port 5000 --env-file .env` (from the project root). `--env-file` is required for uvicorn to actually pick up keys from `.env`; without it, `.env` values are never loaded and `/generate` will fail with "OPENROUTER_API_KEY is not set".
3. Serve the frontend (see "Running the Frontend" below) and open it in a browser.
4. Pick a JLPT level from the dropdown (defaults to N3- shapes how the generated definition/nuance/example sentence are worded, not which words can be looked up), enter a word, click Generate, review/edit the fields, then click Export to Anki (requires Anki running locally with the AnkiConnect add-on).

For multiple words at once, use the Batch Upload section: a `.txt` file with one word per line (kanji/kana only, max 12 words), e.g.:

```text
猫
犬
大人
大前提
```

Click "Generate from File" to get a horizontally-scrollable carousel of cards, one per word. Results stream in as each word finishes rather than waiting for the whole batch, with a live "X/N done" progress counter above the carousel. Each card is independently editable, discardable, and exportable, same as the single-word flow. If a word fails to generate, its card shows the error and the rest of the batch still completes; a malformed file (wrong characters, too many words) is rejected with an error before anything is generated.

For JLPT N2 sample data, use the "Generate from Dataset (N2)" section: pick Vocab, Grammar, or Reading and click "Generate from Dataset" to generate cards from the matching local `data/n2/*.json` file (see `ARCHITECTURE.md`), no typing or file upload needed. Grammar and Reading cards have their own field layout (pattern/connection/meaning/etc. for Grammar; topic/passage/question/etc. for Reading) rather than the vocab fields, since neither is a single word. Each exported card from this section gets an extra Anki tag identifying its section (`N2::Vocab`, `N2::Grammar`, or `N2::Reading`), alongside the usual `anki-tool-v2` tag. This flow doesn't use Postgres at all- re-exporting the same item shows "Already in Anki" instead of creating a duplicate note, via AnkiConnect's own duplicate check rather than a database lookup. Listening is not included yet.

## Configuration

- `OPENROUTER_API_KEY`: authenticates with the OpenRouter API used for card generation; leave empty in `.env` and fill in your own key (see PROMPTS.md).
- `OPENROUTER_MODELS`: comma-separated list of candidate models, tried in order via OpenRouter's built-in model fallback (default: a few free-tier models; see PROMPTS.md).
- `JLPT_LEVEL_DEFAULT`: fallback JLPT level (`N5`-`N1`, default `N3`) used to cater generated definitions/nuance/example sentences to a learner's proficiency, when a request doesn't specify one. The frontend's "JLPT level" dropdown sends its own value on every request, so this only matters if that request field is omitted (see PROMPTS.md). Not to be confused with the per-card `jlpt_level` field, which is the model's own estimate of the target word's difficulty.
- `ANKICONNECT_URL`: AnkiConnect endpoint (default: `http://localhost:8765`).
- `ANKI_DECK_NAME` / `ANKI_NOTE_TYPE`: target deck and note type for export (default: `Japanese` / `Japanese Note Type` in `full` mode, `Basic` in `basic` mode- see `ANKI_EXPORT_MODE` below).
- `ANKI_EXPORT_MODE`: `full` (default) sends each field individually (`Expression`, `Reading`, `Definition`, `Nuance`, `Synonyms`, `Antonyms`, `Example`, `Jlpt`) to a custom note type. `ANKI_NOTE_TYPE` defaults to `Japanese Note Type` in this mode- if that note type doesn't already exist in Anki, the first `full`-mode export creates it automatically via AnkiConnect's `createModel` action, with those eight fields and a basic front/back template, so this works with zero manual Anki setup. An existing note type with that name is left untouched (`createModel` is only ever called to create, never to update). `basic` folds all eight fields into `Front`/`Back` instead, for Anki's stock `Basic` note type- a zero-config fallback with only two fields. Set `ANKI_NOTE_TYPE` yourself to use a different note type name in either mode.
- `ANKI_GRAMMAR_NOTE_TYPE` / `ANKI_READING_NOTE_TYPE`: same idea as `ANKI_NOTE_TYPE`, but for the dataset-driven Grammar/Reading sections (default: `Japanese Grammar Note Type` / `Japanese Reading Note Type` in `full` mode, `Basic` in `basic` mode)- auto-created the same way on first export in `full` mode. `ANKI_EXPORT_MODE`/`ANKI_DECK_NAME` apply to these too; there's no separate mode setting per section.

## Troubleshooting

### Generation seems hung/never comes back

`/generate`'s call to OpenRouter uses a 180s timeout that resets on every byte received (see `PROMPTS.md`), so a slow-but-still-trickling response can look stuck well past what feels reasonable. Isolate whether the delay is this project's code, your network, or the model itself by hitting OpenRouter directly with curl, bypassing the backend entirely:

```bash
curl -w "\nTTFB: %{time_starttransfer}s  Total: %{time_total}s\n" -X POST https://openrouter.ai/api/v1/chat/completions -H "Authorization: Bearer $OPENROUTER_API_KEY" -H "Content-Type: application/json" -d '{"models":["google/gemma-4-26b-a4b-it:free"],"messages":[{"role":"user","content":"say hello"}]}'
```

- **Curl comes back fast, the app doesn't:** the delay is in this project's code (check whether `generate_card()`'s word-drift retry fired twice- see `backend/llm.py`) or something local (network path, machine load), not the model or OpenRouter itself.
- **Curl is slow too, with a low TTFB but long total time:** the model is genuinely taking a while to reason before emitting the final JSON- a model/provider characteristic, not a bug here.
- **Curl is slow with a high TTFB:** the request itself is taking a while to get any response- more likely your network path or OpenRouter-side queueing than the model actively working.
- **Plain chat (drop `response_format` from the payload above) is fast but structured output is slow:** the `json_schema` structured-output requirement is adding the overhead, not a bug in this project.

See `PROMPTS.md`'s change log for the incident that established this technique.

## Project docs

- [PROJECT.md](PROJECT.md): goals and scope.
- [ARCHITECTURE.md](ARCHITECTURE.md): pipeline design.
- [PROMPTS.md](PROMPTS.md): LLM prompt templates.
- [DATABASE.md](DATABASE.md): storage schema.
- [ROADMAP.md](ROADMAP.md): planned work.
- [diagrams/](diagrams/README.md): PlantUML source diagramming architecture and workflows.

## Running the Frontend

The frontend is a static HTML/JS app in `frontend/` (`index.html` + `index.js`), run
directly in a regular browser. This is the actual UI, not a placeholder for a desktop
shell.

It expects a backend at `http://localhost:5000` exposing `/generate`, `/generate/batch`,
`/generate/dataset`, `/export`, `/export/dataset-vocab`, `/export/grammar`, and
`/export/reading`. If the backend is unreachable, clicking Generate or Export will
surface the connection-error messaging described in PROJECT.md's error handling
section.

## Chrome extension

For a faster single-word workflow with no review step, `extension/` is a Chrome (Manifest
V3) extension: paste a word into its popup, and it's generated and exported to Anki
automatically in the background, with a desktop notification when each one finishes.
Multiple words can be submitted back-to-back without waiting for earlier ones to finish.
It calls a dedicated `POST /generate/export` endpoint on the same backend (see
`backend/main.py`) that combines generation and export server-side. Editing generated
cards, resolving duplicates, and batch upload are still web-app-only - the popup links
there. See [extension/README.md](extension/README.md) for setup and known limitations.

`python scripts/dev.py` (see Usage above) starts this automatically. To run it standalone:

1. From the project root: `cd frontend`.
2. Serve it locally: `python -m http.server 8080`.
3. Open `http://localhost:8080` in a browser.

(Opening `index.html` directly via `file://` also works for now.)
