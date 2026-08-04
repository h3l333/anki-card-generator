# Database

## Purpose

What gets persisted between pipeline runs and why (e.g. caching LLM output after user editing so re-runs don't regenerate cards, tracking export status).

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

| Column           | Type    | Notes                 |
| ---------------- | ------- | --------------------- |
| word_id          | INTEGER | FK → words.id         |
| definition_ja    | TEXT    |                       |
| nuance           | TEXT    |                       |
| example_sentence | TEXT    |                       |
| jlpt_level       | TEXT    |                       |
| exported         | BOOLEAN | already sent to Anki? |
