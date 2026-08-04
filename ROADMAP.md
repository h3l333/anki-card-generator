# Roadmap

Planned and proposed work that hasn't been built yet. Distinct from `PROJECT.md`
(current goals/non-goals) and `ARCHITECTURE.md` (how the system works today).
Entries here are ideas or queued tasks, not settled scope.

## Feature ideas

### Yomitan dictionary integration

Let the user optionally include definitions from local Yomitan-format
dictionaries alongside the AI-generated `definition_ja`, rather than relying
solely on the LLM.

- Yomitan dictionaries are `.zip` archives of JSON (`index.json` plus `term_bank_N.json` files, each entry roughly `[term, reading, tags, rules, score, glossary, sequence, tags]`). Parsing happens locally; no network calls are made.
- Proposed approach: a `backend/yomitan.py` module that parses a directory of dictionary `.zip` files (path set via an env var) into an in-memory term-to-glossary index built once at backend startup. `/generate` would also look up the word in that index and return any matches alongside the LLM-generated fields; the review UI would show both side-by-side for the user to merge/edit before export.
- **Tradeoff:** an in-memory index is simplest to build first, but adds to
  startup time as more/larger dictionaries are added and doesn't persist
  across restarts. Indexing into the existing (currently unused) Postgres
  container instead would be faster and persistent, at the cost of building
  that ingestion path now rather than later.
- **Note:** this would reverse `PROJECT.md`'s current non-goal "No Yomitan export
  parsing or browser extension hooks". That line needs revisiting if this
  goes ahead. The scope here is parsing Yomitan's dictionary file format as a
  data source, not hooking into the Yomitan browser extension itself.

## Engineering tasks

- **Test suite:** No automated tests exist yet. Planned approach: `pytest` +
  FastAPI's `TestClient` (via `httpx`), with `tests/` mirroring `backend/`,
  mocking `requests.post` in `llm.py` and `anki.py` (via `unittest.mock.patch`
  or `requests-mock`) so tests don't hit OpenRouter or AnkiConnect for real.
- **Postgres persistence:** `docker-compose.yml` already runs the `postgres`
  service and `DATABASE.md` documents an intended `words`/`cards` schema, but
  `backend/db.py` is currently empty and nothing in `backend/` connects to it
  yet.
- **Code documentation:** Add more in-repo comments/notes for personal
  understanding of the codebase, beyond what's in the project docs.
- **UML diagrams:** Diagram the repo's structure and data flow to make the
  architecture easier to reason about at a glance.
