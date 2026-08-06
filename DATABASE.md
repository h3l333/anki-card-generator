# Database

## Purpose

Two things, both driven by the same goal- never spend an LLM call on a word that's
already been generated:

- **Caching the raw LLM output.** A word's card is persisted to Postgres as soon as it
  comes back from OpenRouter, *before* the user edits anything in the review form (see
  `ARCHITECTURE.md`). That means the `cards` row always reflects the model's original
  output, independent of whatever edits happen on the way to Anki.
- **Tracking export history.** Every time a card is pushed to Anki- whether that's the
  first time or a later re-export after further edits- an `exports` row records which
  Anki note that export produced. That's what lets a later re-export update the existing
  Anki note (`updateNoteFields`) instead of creating a duplicate one (`addNote`).

## Storage choice

Postgres, running in its own Docker container (see `docker-compose.yml`, service
`postgres`), accessed over TCP on port `5432`. Chosen over SQLite specifically to
avoid the file/volume-sharing problem of a file-based DB living in a separate
container from the Python backend. Postgres exposes a normal network port instead,
so the backend just needs a connection string, not a shared bind mount.

Credentials are supplied via `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`
env vars (defaults in `docker-compose.yml` are for local dev only; override via a
local, uncommitted `.env` file if that matters to you).

## Schema

### `words` (or equivalent)

| Column     | Type      | Notes                               |
| ---------- | --------- | ----------------------------------- |
| id         | SERIAL PK |                                     |
| kanji      | TEXT      |                                     |
| reading    | TEXT      |                                     |
| source     | TEXT      | e.g. `manual` or `batch:<filename>` |
| created_at | TIMESTAMP |                                     |

### `cards` (generated content)

| Column           | Type    | Notes                                        |
| ---------------- | ------- | --------------------------------------------- |
| word_id          | INTEGER | PK, FK → words.id (one card per word, ever)   |
| definition_ja    | TEXT    |                                                |
| nuance           | TEXT    |                                                |
| synonyms         | TEXT    | comma-separated; "該当なし" if none apply       |
| antonyms         | TEXT    | comma-separated; "該当なし" if none apply       |
| example_sentence | TEXT    |                                                |
| jlpt_level       | TEXT    |                                                |
| exported         | BOOLEAN | has this word ever been exported at all?      |

Write-once: a row is inserted the moment the LLM responds, and never updated afterwards.
User edits made in the review form are never written back here- see `ARCHITECTURE.md`.

### `exports` (export history)

| Column        | Type      | Notes                                            |
| ------------- | --------- | ------------------------------------------------- |
| id            | SERIAL PK |                                                    |
| word_id       | INTEGER   | FK → words.id, not unique (many rows per word)    |
| anki_note_id  | BIGINT    | the note ID AnkiConnect assigned on `addNote`      |
| exported_at   | TIMESTAMP |                                                    |

One row per export *event*, not per word- re-exporting an already-exported word (after
further edits) adds a new row rather than overwriting the old one, so the table doubles
as a history log. The most recent row for a `word_id` is what tells the backend which
Anki note to target with `updateNoteFields` on a re-export, instead of creating a
duplicate note via `addNote`.
