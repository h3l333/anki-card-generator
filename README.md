# Anki Tool v2

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

## Usage

1. Start the database container: `docker compose up -d`.
2. Start the backend: `uvicorn backend.main:app --reload --port 5000 --env-file .env` (from the project root). `--env-file` is required for uvicorn to actually pick up keys from `.env`; without it, `.env` values are never loaded and `/generate` will fail with "OPENROUTER_API_KEY is not set".
3. Serve the frontend (see "Running the Frontend" below) and open it in a browser.
4. Enter a word, click Generate, review/edit the fields, then click Export to Anki (requires Anki running locally with the AnkiConnect add-on).

For multiple words at once, use the Batch Upload section: a `.txt` file with one word per line (kanji/kana only, max 12 words), e.g.:

```text
猫
犬
大人
大前提
```

Click "Generate from File" to get a horizontally-scrollable carousel of cards, one per word. Each is independently editable, discardable, and exportable, same as the single-word flow. If a word fails to generate, its card shows the error and the rest of the batch still completes; a malformed file (wrong characters, too many words) is rejected with an error before anything is generated.

## Configuration

- `OPENROUTER_API_KEY`: authenticates with the OpenRouter API used for card generation; leave empty in `.env` and fill in your own key (see PROMPTS.md).
- `OPENROUTER_MODELS`: comma-separated list of candidate models, tried in order via OpenRouter's built-in model fallback (default: a few free-tier models; see PROMPTS.md).
- `ANKICONNECT_URL`: AnkiConnect endpoint (default: `http://localhost:8765`).
- `ANKI_DECK_NAME` / `ANKI_NOTE_TYPE`: target deck and note type for export (default: `Japanese` / `Basic`). `Basic` is a zero-config fallback with only Front/Back fields. Set up a custom note type matching the eight card fields and point these vars at it for a better fit.
- `ANKI_EXPORT_MODE`: `basic` (default) folds all eight fields into `Front`/`Back` for Anki's stock `Basic` note type; `full` sends each field individually (`Expression`, `Reading`, `Definition`, `Nuance`, `Synonyms`, `Antonyms`, `Example`, `Jlpt`) for a custom note type with matching field names. Use `full` together with `ANKI_NOTE_TYPE` pointed at that custom note type.

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
and `/export`. If the backend is unreachable, clicking Generate or Export will surface
the connection-error messaging described in PROJECT.md's error handling section.

1. From the project root: `cd frontend`.
2. Serve it locally: `python -m http.server 8080`.
3. Open `http://localhost:8080` in a browser.

(Opening `index.html` directly via `file://` also works for now.)
