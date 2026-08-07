# System Architecture & Data Flow

## Card Generation & Review Workflow

```mermaid
flowchart TD
    UserInput[User Input] -->|single word| BrowserUI[Browser UI]
    BatchInput[".txt file upload"] -->|one word per line| BrowserUI

    BrowserUI -->|"single word: HTTP request"| Lookup[Python Backend]
    Lookup -->|"Postgres lookup by kanji, see DATABASE.md"| Duplicate{Already generated?}
    Duplicate -->|"yes- no LLM call"| ReviewForm["Browser UI Form<br/>USER EDITS HERE"]
    Duplicate -->|no| Generate[Python Backend]

    BrowserUI -->|"batch: HTTP request, no duplicate check"| Generate

    Generate -->|"HTTPS prompt request (per word, if batch)"| OpenRouter[OpenRouter API]
    OpenRouter -->|structured JSON response| Persist[Python Backend]
    Persist -->|"Postgres insert (raw LLM output, before any edit)"| ReviewForm

    ReviewForm -->|user submits final edited card| Validate[Python Backend]
    Validate -->|"validation and export-history lookup, see DATABASE.md"| Export[Python Backend]
    Export -->|"AnkiConnect REST API (addNote, or updateNoteFields if a prior export exists)"| Anki[Anki Desktop]
    Anki -->|note ID| Record["Python Backend: record export event"]
```

### Flow Breakdown

1. **Generation Trigger:**
   - User inputs a single word or uploads a `.txt` file in the browser.
   - The browser passes the target word to the Python backend via HTTP.

2. **Duplicate Check (single word only, before any LLM call):**
   - Python looks the word up in Postgres (`words`/`cards`, see `DATABASE.md`) by kanji text.
   - **Not found:** proceed to generation (step 3) as normal- no tokens have been spent yet either way.
   - **Found:** no LLM call is made. Python returns the existing card straight from Postgres, and the browser shows it pre-filled with an informational banner ("This word already has a saved card- showing the existing one."). The user reviews/edits/exports it exactly like a freshly generated card, or discards it via the normal Discard button- there's no separate cancel-vs-fetch choice dialog. (A fuller notify-then-choose UX was once planned here; it was never built, and this section used to describe that unbuilt version instead of what `frontend/index.js` actually does.)
   - **Batch `.txt` upload does not do this check at all.** Every word in an uploaded file is sent to the LLM regardless of whether it's already in Postgres- there's no per-word duplicate lookup, and today no way to skip an already-generated word without spending a fresh LLM call on it. Whether to add that is a deliberate, separate decision (see `ROADMAP.md`), not assumed here.

3. **LLM Execution & Parsing:**
   - Python requests structured JSON from the OpenRouter API over HTTPS- for whichever word(s) reach this step: a single word that wasn't already in Postgres (step 2), or every word in a batch upload regardless of Postgres state.
   - If response is malformed JSON, Python raises a formatting error to the browser UI. In the batch flow, one word's failure is caught individually and doesn't abort the rest of the batch (`backend/llm.py::generate_cards_batch`)- see `ROADMAP.md`.
   - As soon as a valid response comes back, Python writes it to Postgres immediately (`cards` row, write-once content- see `DATABASE.md`), *before* it's shown to the user- for both the single-word and batch flows alike. This is what makes the persisted card always equal to the model's raw output regardless of what happens in step 4, and what gives every successfully-generated word (single or batch) a `word_id` for the export step below.

4. **User Review State:**
   - Python sends the draft payload (freshly generated, or fetched from Postgres per step 2) to the browser, along with the `word_id` Postgres assigned it.
   - The browser renders editable `<input>` and `<textarea>` controls pre-filled with generated fields: `[Expression, Reading, Monolingual Definition, Nuance, Synonyms, Antonyms, Example, JLPT]`.
   - The user modifies any field manually. These edits are never written back to the `cards` table- they only ever flow forward into Anki (step 5).

5. **Export:**
   - Upon clicking "Export to Anki", Python checks Postgres for a prior export of this word (`exports` table, see `DATABASE.md`), using the `word_id` carried alongside the card since step 3/4- single-word and batch cards both have one now.
   - **No prior export:** Python posts the finalized payload to AnkiConnect (`http://localhost:8765`) as a new note (`addNote`).
   - **Prior export exists:** Python calls AnkiConnect's `updateNoteFields` against that export's note ID instead, so the existing Anki note is rewritten rather than duplicated.
   - Either way, a successful AnkiConnect call is recorded as a new row in the `exports` table.
   - If Anki is unreachable, UI displays connection error without discarding user edits, and nothing is written to `exports`.
