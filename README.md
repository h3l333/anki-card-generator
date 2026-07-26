# Anki Tool v2

Generate Japanese Anki flashcards using a local LLM (via Ollama).

## Prerequisites

- Docker / Docker Compose
- Python 3.x
- Anki (with AnkiConnect, if using that export path)

## Setup

1. `docker compose up -d`
2. Pull the model: `docker exec -it ollama_japanese_llm ollama pull <model>`
3. Install Python deps: `pip install -r requirements.txt`

## Usage

<!-- how to run the import -> generate -> export pipeline once it exists -->

## Configuration

<!-- env vars, model name, Ollama host/port -->

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
