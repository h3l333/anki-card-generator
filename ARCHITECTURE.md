# System Architecture & Data Flow

## Card Generation & Review Workflow

```text
[User Input]
     │ (Single Word or .txt file)
     ▼
[Electron UI]
     │ (IPC / HTTP Request)
     ▼
[Python Backend]
     │ (Prompt JSON)
     ▼
[Ollama Container]
     │ (Structured JSON Response)
     ▼
[Electron UI Form]  <-- USER EDITS HERE
     │ (User submits final edited card)
     ▼
[Python Backend]
     │ (Validation & Local SQLite Sync)
     ▼
[Python Backend]
     │ (AnkiConnect REST API)
     ▼
[Anki Desktop]
```

### Flow Breakdown

1. **Generation Trigger:**
   - User inputs a single word or uploads a `.txt` file in Electron.
   - Electron passes the target word to the Python backend.

2. **LLM Execution & Parsing:**
   - Python requests structured JSON from local Ollama (`http://localhost:${OLLAMA_PORT:-11434}`).
   - If response is malformed JSON, Python raises a formatting error to Electron UI.

3. **User Review State:**
   - Python sends draft payload to Electron.
   - Electron renders editable `<input>` and `<textarea>` controls pre-filled with generated fields: `[Expression, Reading, Monolingual Definition, Nuance, Example, JLPT]`.
   - The user modifies any field manually.

4. **Persistence & Export:**
   - Drafts are recorded in local SQLite container database AFTER user edits have been made.
   - Upon clicking "Export to Anki", Python posts the finalized payload to AnkiConnect (`http://localhost:8765`).
   - If Anki is unreachable, UI displays connection error without discarding user edits.
