# Project Overview: Japanese Anki Card Generator

## Goal

Generate high-quality Japanese Anki flashcards using local LLMs (via Ollama in Docker) with a desktop review interface, exporting directly to Anki.

## Target Users

Intermediate and advanced Japanese learners who want fast, nuanced monolingual cards without relying on cloud APIs.

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
  - Theme Color (e.g., card background / accent colors)
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

### Desktop Frontend

- **Framework:** Electron (Node.js / Web Technologies).
- **Role:** Handles desktop UI, file uploads (`.txt`), single-word input, interactive card editor/preview, CSS theme/font configuration, and error state alerts.

### Backend & AI Pipeline

- **Language:** Python 3.11+.
- **Role:** Main application logic, prompt engineering, JSON response parsing, AnkiConnect HTTP requests, and database persistence.
- **Local AI Setup:** Ollama running in a Docker container.
  - **Default Port:** `11434` (must be configurable via environment variable, e.g., `OLLAMA_PORT`).
  - **Requirement:** Python backend communicates with Ollama using structured JSON output enforcement.

### Data Persistence

- **Database:** SQLite running inside its own isolated container or persistent storage location to save history, card drafts, and app configurations.

### App Deployment (Current Phase)

- Launched via a simple local Python execution script bridging the Electron shell and backend service.

---

## Integrations & External Systems

1. **Ollama Docker Container**
   - Address: `http://localhost:${OLLAMA_PORT:-11434}`
   - Role: Local LLM engine serving card content.

2. **Anki Desktop & AnkiConnect Add-on**
   - Address: `http://localhost:8765`
   - Role: Card ingestion target via HTTP API.

---

## Error Handling & Resiliency Expectations

The UI must present explicit, user-friendly error dialogs/notifications for key failure points:

- **Anki Connection Failure:** If Anki is closed or AnkiConnect is unreachable, prompt the user: _"Unable to reach Anki. Please ensure Anki is running with the AnkiConnect add-on enabled."_
- **LLM Parsing Error:** If Ollama returns invalid or malformed JSON, inform the user: _"Failed to parse LLM response due to formatting errors. Please retry generation."_
