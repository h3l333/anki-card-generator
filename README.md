# Anki Tool v2

Generate Japanese Anki flashcards using the OpenRouter API (free-tier LLM access).

## Prerequisites

- Docker/Docker Compose (for the Postgres container)
- Python 3.x
- An OpenRouter API key (free tier available)
- Anki (with AnkiConnect, if using that export path)

## Setup

1. `docker compose up -d` (starts the Postgres container)
2. Set `OPENROUTER_API_KEY` as an environment variable (or in `.env`)- see Configuration
3. Install Python deps: `pip install -r requirements.txt`

## Usage

1. Start the database container: `docker compose up -d`
2. Start the backend: `uvicorn backend.main:app --reload --port 5000` (from the project root)
3. Serve the frontend (see "Running the Frontend" below) and open it in a browser
4. Enter a word, click Generate, review/edit the fields, then click Export to Anki (requires Anki running locally with the AnkiConnect add-on)

For multiple words at once, use the Batch Upload section: a `.txt` file with one word per line (kanji/kana only, max 12 words), e.g.:

```
猫
犬
大人
大前提
```

Click "Generate from File" to get a horizontally-scrollable carousel of cards, one per word- each is independently editable, discardable, and exportable, same as the single-word flow. If a word fails to generate, its card shows the error and the rest of the batch still completes; a malformed file (wrong characters, too many words) is rejected with an error before anything is generated.

## Configuration

- `OPENROUTER_API_KEY`- authenticates with the OpenRouter API used for card generation; leave empty in `.env` and fill in your own key (see PROMPTS.md).
- `OPENROUTER_MODEL`- selects which model OpenRouter routes the request to (default: a free-tier model- see PROMPTS.md).
- `ANKICONNECT_URL`- AnkiConnect endpoint (default: `http://localhost:8765`).
- `ANKI_DECK_NAME` / `ANKI_NOTE_TYPE`- target deck and note type for export (default: `Japanese` / `Basic`). `Basic` is a zero-config fallback with only Front/Back fields- set up a custom note type matching the six card fields and point these vars at it for a better fit.

## Project docs

- [PROJECT.md](PROJECT.md) - goals and scope
- [ARCHITECTURE.md](ARCHITECTURE.md) - pipeline design
- [PROMPTS.md](PROMPTS.md) - LLM prompt templates
- [DATABASE.md](DATABASE.md) - storage schema
- [API.md](API.md) - internal module interfaces
- [ROADMAP.md](ROADMAP.md) - planned work

## Running the Frontend

The frontend is a static HTML/JS app in `frontend/` (`index.html` + `index.js`), run
directly in a regular browser- this is the actual UI, not a placeholder for a desktop
shell.

It expects a backend at `http://localhost:5000` exposing `/generate`, `/generate/batch`,
and `/export`. If the backend is unreachable, clicking Generate or Export will surface
the connection-error messaging described in PROJECT.md's error handling section.

1. From the project root: `cd frontend`
2. Serve it locally: `python -m http.server 8080`
3. Open `http://localhost:8080` in a browser

(Opening `index.html` directly via `file://` also works for now.)
