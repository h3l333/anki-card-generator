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

The "never spend an LLM call twice" goal is enforced for both flows: `/generate` and
`/generate/batch` both call `find_word_by_kanji` before generating, per word in the
batch case. A hit returns the existing card straight from Postgres (`duplicate=True`,
reusing the existing `word_id`) instead of spending a fresh LLM call; only genuinely
new words get a fresh `words`/`cards` row (see `ARCHITECTURE.md`).

`find_word_by_kanji` matches on kanji **and** `words.level` together- the same word
requested at a different JLPT level is treated as a new word, since its card's language
would need regenerating for the new audience. See `PROMPTS.md` for how `level` shapes
the generation prompt. A composite index on `(kanji, level)` (`backend/db.py`'s
`ix_words_kanji_level`) backs this lookup- like the `level` column itself, `create_all()`
won't add this index to a `words` table that already exists, so it needs a hand-run
`CREATE INDEX ix_words_kanji_level ON words (kanji, level);` in that case.

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
| level      | TEXT      | JLPT level (N5-N1) the card's language was generated for; part of the duplicate-check lookup, so the same kanji at a different level is a separate row |
| source     | TEXT      | `manual` (single-word flow) or `batch` (batch flow)- no filename is captured |
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

Write-once content: a row is inserted the moment the LLM responds, and its generated
columns (`definition_ja`, `nuance`, `synonyms`, `antonyms`, `example_sentence`,
`jlpt_level`) are never updated afterwards. User edits made in the review form are never
written back here- see `ARCHITECTURE.md`. The one exception is `exported`: `record_export()`
(see below) flips it to `true` after a successful export, so the row isn't literally
immutable end to end- just its LLM-generated content.

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

## What this schema does *not* cover: dataset-driven generation

The Vocab/Grammar/Reading dataset-driven flow (`backend/datasets.py`, `POST
/generate/dataset`, `POST /export/grammar`, `POST /export/reading`, `POST
/export/dataset-vocab`- see `ARCHITECTURE.md`) deliberately **does not touch any table
on this page**. Nothing it generates is inserted into `words`/`cards`, and nothing it
exports is recorded into `exports`. This is a considered decision, not an oversight:

- The schema above is vocab-shaped (`words.kanji`/`words.reading`)- Grammar and Reading
  don't fit it (a grammar pattern isn't a kanji/reading pair, a reading passage isn't a
  word at all).
- There's no migration tool in this repo (see `ROADMAP.md`)- `init_db()`'s `create_all()`
  only creates tables that don't exist yet, it never retrofits new columns/indexes onto
  ones that do (the `level` column and its index above both needed a hand-run SQL
  statement for exactly this reason). Adding a clean set of new tables for two more
  content types, plus deciding how `exports`-style history would generalize across three
  very different "what got exported" shapes, is real schema work that isn't required for
  a first version of this feature.

Instead, duplicate protection for this flow happens at export time via AnkiConnect
itself: `backend/anki.py`'s `_add_note_checked` calls `addNote` with
`allowDuplicate: False` and reads AnkiConnect's own null-result signal (a note whose
first/front field already matches one in that note type) as "already exists", rather
than a Postgres lookup deciding it up front. Every dataset-driven export is a fresh
`addNote`- there's no `updateNoteFields` re-export path for this flow, since there's no
persisted note ID anywhere to target one with.

Adding real persistence for this flow later is possible (new `grammar_points`/
`grammar_cards` and `reading_passages`/`reading_cards` tables mirroring `words`/`cards`
would need only `CREATE TABLE`s, not `ALTER TABLE`s, since they'd be new tables) but is
explicitly deferred- see `ROADMAP.md`.
