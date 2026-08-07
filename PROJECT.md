# Project Overview: Japanese Anki Card Generator

## Goal

Generate high-quality Japanese Anki flashcards using the OpenRouter API (free-tier LLM access) with a browser-based review interface, exporting directly to Anki.

## Target Users

Intermediate and advanced Japanese learners who want fast, nuanced monolingual cards without paying for LLM access or running local model infrastructure.

## Core Features

### 1. Card Generation & AI Processing

- **Monolingual Definition:** Generate Japanese-to-Japanese definitions appropriate for intermediate/advanced learners.
- **Nuance Explanation:** Detail usage notes, formality, and subtle differences between similar words.
- **Synonyms & Antonyms:** Surface similar- and opposite-meaning words alongside the target word, for ease of understanding.
- **Context Sentences:** Generate natural example sentences, plain kanji/kana text with no furigana (see `PROMPTS.md`- furigana was deliberately dropped from the prompt after the model invented ad hoc notation for it).
- **JLPT Estimation:** Estimate the JLPT level (N5 to N1) for the target word.

### 2. User Input & Workflow

- **Single Word Input:** Fast entry for one word at a time via the UI.
- **Batch Text Upload:** Upload a `.txt` file containing a list of words to process sequentially (one by one).
- **Interactive Card Review/Edit:** UI displays the generated card fields before export, allowing the user to inspect, modify, or reject fields before sending to Anki.

### 3. Anki Integration & Styling

- **AnkiConnect Export:** Push approved cards directly to Anki via the AnkiConnect add-on.
- **Card Customization:** Allow users to set basic CSS preferences in the UI:
  - Theme Color (e.g., card background/accent colors).
  - Font Family.

## Non-goals

- No Yomitan export parsing or browser extension hooks.
- No automatic vocabulary mining from anime, manga, or websites.
- No mobile applications.
- No collaborative or multi-user features.
- No built-in spaced repetition algorithm (delegated to Anki).
- No user authentication or user accounts.
- No support for non-Japanese target languages.
- No AI image generation for cards.

## Technical Stack & Architecture

### Frontend

- **Framework:** Static HTML/CSS/JS, run in a standard web browser.
- **Role:** Handles UI, file uploads (`.txt`), single-word input, interactive card editor/preview, CSS theme/font configuration, and error state alerts.

### Backend & AI Pipeline

- **Language:** Python 3.11+.
- **Role:** Main application logic, prompt engineering, JSON response parsing, AnkiConnect HTTP requests, and database persistence.
- **AI Setup:** OpenRouter (cloud LLM routing API, free-tier models), called directly over HTTPS. No local model, GPU, or Ollama container is required.
  - **Provider:** OpenRouter is the fixed provider. A list of candidate models is configurable via `OPENROUTER_MODELS`, with OpenRouter itself falling back through the list if one is unavailable.
  - **Requirement:** Python backend requests structured JSON output from the configured provider's API and validates it against the card schema.

### Data Persistence

- **Database:** Postgres running in its own Docker container (see `DATABASE.md`) to save history and card drafts.

### App Deployment (Current Phase)

- Backend and frontend run as independent processes (see README "Running the Frontend"). No desktop shell or bridging script is needed.

## Integrations & External Systems

1. **OpenRouter (Cloud LLM API):**
   - **Address:** `https://openrouter.ai/api/v1` (no local port).
   - **Role:** Generates card content (definition, nuance, synonyms, antonyms, example, JLPT estimate) from a free-tier API key.

2. **Anki Desktop & AnkiConnect Add-on:**
   - **Address:** `http://localhost:8765`.
   - **Role:** Card ingestion target via HTTP API.

## Error Handling & Resiliency Expectations

This section describes the error messages `frontend/index.js` actually shows today, not a separate target spec- update it alongside any change to that file's error handling.

- **Anki Connection Failure:** if Anki is closed or AnkiConnect is unreachable, both the single-word and batch export flows show the same message: _"Unable to reach Anki. Please ensure Anki is running with the AnkiConnect add-on enabled."_
- **Generation Failure (single word):** network failures and LLM/parsing failures aren't distinguished- both surface the same generic message: _"Failed to reach the backend or parse its response. Is the Python service running?"_
- **Generation Failure (batch, per word):** shows the backend's specific error detail when one is available (e.g. a malformed-JSON or word-drift message raised by `backend/llm.py`), falling back to a generic _"Failed to reach the backend..."_ message otherwise. One word's failure doesn't abort the rest of the batch, and its carousel card shows a hint recommending the user retry that word via the single-word form.
