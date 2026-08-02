# System Architecture & Data Flow

## Card Generation & Review Workflow

```text
[User Input]
     │ (Single Word or .txt file)
     ▼
[Browser UI]
     │ (HTTP Request)
     ▼
[Python Backend]
     │ (HTTPS Prompt Request)
     ▼
[OpenRouter API]
     │ (Structured JSON Response)
     ▼
[Browser UI Form]  <-- USER EDITS HERE
     │ (User submits final edited card)
     ▼
[Python Backend]
     │ (Validation & Postgres Sync)
     ▼
[Python Backend]
     │ (AnkiConnect REST API)
     ▼
[Anki Desktop]
```

### Flow Breakdown

1. **Generation Trigger:**
   - User inputs a single word or uploads a `.txt` file in the browser.
   - The browser passes the target word to the Python backend via HTTP.

2. **LLM Execution & Parsing:**
   - Python requests structured JSON from the OpenRouter API over HTTPS.
   - If response is malformed JSON, Python raises a formatting error to the browser UI.

3. **User Review State:**
   - Python sends draft payload to the browser.
   - The browser renders editable `<input>` and `<textarea>` controls pre-filled with generated fields: `[Expression, Reading, Monolingual Definition, Nuance, Example, JLPT]`.
   - The user modifies any field manually.

4. **Persistence & Export:**
   - Drafts are recorded in the Postgres database (see `DATABASE.md`) AFTER user edits have been made.
   - Upon clicking "Export to Anki", Python posts the finalized payload to AnkiConnect (`http://localhost:8765`).
   - If Anki is unreachable, UI displays connection error without discarding user edits.
