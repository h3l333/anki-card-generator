# Project Overview: Japanese Anki Card Generator

## Goal

Generate high-quality Japanese Anki flashcards using the OpenRouter API (free-tier LLM access) with a browser-based review interface, exporting directly to Anki.

## Target Users

Intermediate and advanced Japanese learners who want fast, nuanced monolingual cards without paying for LLM access or running local model infrastructure.

## Core Features

### 1. Card Generation & AI Processing

- **Monolingual Definition:** Generate Japanese-to-Japanese definitions appropriate for intermediate/advanced learners.
- **Nuance Explanation:** Detail usage notes, formality, and subtle differences between similar words.
- **Context Sentences:** Generate natural example sentences with furigana/readings.
- **JLPT Estimation:** Estimate the JLPT level (N5 to N1) for the target word.

### 2. User Input & Workflow

- **Single Word Input:** Fast entry for one word at a time via the UI.
- **Batch Text Upload:** Upload a `.txt` file containing a list of words to process sequentially (one by one).
- **Interactive Card Review/Edit:** UI displays the generated card fields before export, allowing the user to inspect, modify, or reject fields before sending to Anki.

### 3. Anki Integration & Styling

- **AnkiConnect Export:** Push approved cards directly to Anki via the AnkiConnect add-on.
- **Card Customization:** Allow users to set basic CSS preferences in the UI:
  - Theme Color (e.g., card background/accent colors)
  - Font Family

## Non-goals

- No Yomitan export parsing or browser extension hooks.
- No automatic vocabulary mining from anime, manga, or websites.
- No mobile applications.
- No collaborative or multi-user features.
- No built-in spaced repetition algorithm (delegated to Anki).
- No user authentication or user accounts.
- No support for non-Japanese target languages.
- No AI image generation for cards.

---

## Technical Stack & Architecture

### Frontend

- **Framework:** Static HTML/CSS/JS, run in a standard web browser.
- **Role:** Handles UI, file uploads (`.txt`), single-word input, interactive card editor/preview, CSS theme/font configuration, and error state alerts.

### Backend & AI Pipeline

- **Language:** Python 3.11+.
- **Role:** Main application logic, prompt engineering, JSON response parsing, AnkiConnect HTTP requests, and database persistence.
- **AI Setup:** OpenRouter (cloud LLM routing API, free-tier models), called directly over HTTPS- no local model, GPU, or Ollama container required.
  - **Provider:** OpenRouter is the fixed provider- the underlying model is configurable via `OPENROUTER_MODEL` so different free-tier models can be swapped in.
  - **Requirement:** Python backend requests structured JSON output from the configured provider's API and validates it against the card schema.

### Data Persistence

- **Database:** Postgres running in its own Docker container (see `DATABASE.md`) to save history, card drafts, and app configurations.

### App Deployment (Current Phase)

- Backend and frontend run as independent processes (see README "Running the Frontend")- no desktop shell or bridging script needed.

---

## Integrations & External Systems

1. **OpenRouter (Cloud LLM API)**
   - Address: `https://openrouter.ai/api/v1` (no local port).
   - Role: Generates card content (definition, nuance, example, JLPT estimate) from a free-tier API key.

2. **Anki Desktop & AnkiConnect Add-on**
   - Address: `http://localhost:8765`
   - Role: Card ingestion target via HTTP API.

---

## Error Handling & Resiliency Expectations

The UI must present explicit, user-friendly error dialogs/notifications for key failure points:

- **Anki Connection Failure:** If Anki is closed or AnkiConnect is unreachable, prompt the user: _"Unable to reach Anki. Please ensure Anki is running with the AnkiConnect add-on enabled."_
- **LLM Parsing Error:** If the LLM API returns invalid or malformed JSON, inform the user: _"Failed to parse LLM response due to formatting errors. Please retry generation."_
