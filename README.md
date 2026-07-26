# Anki Tool v2

Generate Japanese Anki flashcards using a local LLM (via Ollama).

## Prerequisites

- Docker / Docker Compose
- Python 3.x
- Anki (with AnkiConnect, if using that export path)

## Setup

1. `docker compose up -d`
2. Pull the model: `docker exec -it ollama_japanese_llm ollama pull yuma/DeepSeek-R1-Distill-Qwen-Japanese:14b`
3. Install Python deps: `pip install -r requirements.txt`

## Usage

1. Start the LLM and database containers: `docker compose up -d`
2. Start the backend: `uvicorn backend.main:app --reload --port 5000` (from the project root)
3. Serve the frontend (see "Running the Frontend" below) and open it in a browser
4. Enter a word, click Generate, review/edit the fields, then click Export to Anki (requires Anki running locally with the AnkiConnect add-on)

Batch `.txt` upload isn't implemented yet - see ROADMAP.md.

## Configuration

- `OLLAMA_HOST` - full URL to the Ollama instance (default: `http://localhost:11435`, matching the host port `docker-compose.yml` maps to the container's `11434`).
- `ANKICONNECT_URL` - AnkiConnect endpoint (default: `http://localhost:8765`).
- `ANKI_DECK_NAME` / `ANKI_NOTE_TYPE` - target deck and note type for export (default: `Japanese` / `Basic`). `Basic` is a zero-config fallback with only Front/Back fields - set up a custom note type matching the six card fields and point these vars at it for a better fit.
- Model: `yuma/DeepSeek-R1-Distill-Qwen-Japanese:14b` (see PROMPTS.md for the prompt and a manual test command).

## Project docs

- [PROJECT.md](PROJECT.md) - goals and scope
- [ARCHITECTURE.md](ARCHITECTURE.md) - pipeline design
- [PROMPTS.md](PROMPTS.md) - LLM prompt templates
- [DATABASE.md](DATABASE.md) - storage schema
- [API.md](API.md) - internal module interfaces
- [ROADMAP.md](ROADMAP.md) - planned work

## Running the Frontend (Prototype)

A minimal HTML/JS frontend prototype lives in `frontend/` (`index.html` + `index.js`).
It's a stand-in for the Electron UI described in ARCHITECTURE.md - useful for shaping
the card review layout before the Electron shell exists.

It expects a backend at `http://localhost:5000` exposing `/generate` and `/export`
endpoints (not implemented yet). Until the backend exists, clicking Generate or Export
will surface the same connection-error messaging described in PROJECT.md's error
handling section.

1. From the project root: `cd frontend`
2. Serve it locally: `python -m http.server 8080`
3. Open `http://localhost:8080` in a browser

(Opening `index.html` directly via `file://` also works for now.)
