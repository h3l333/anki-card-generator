# 3 FastAPI routes
import json
# Used only by _stream_batch_results below- each NDJSON line it yields is a plain dict
# serialized by hand via json.dumps, not a Pydantic model, since StreamingResponse just
# wants raw bytes/str chunks rather than something FastAPI can validate against a
# response_model the way the other routes' return values are.

from collections.abc import Iterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend.anki import AnkiConnectError, export_card
from backend.batch import BatchValidationError, parse_and_validate
from backend.db import (
    find_word_by_kanji,
    get_card,
    get_latest_export,
    init_db,
    insert_card,
    insert_word,
    record_export,
)
from backend.llm import (
    JLPT_LEVEL_DEFAULT,
    LLMError,
    generate_card,
    generate_cards_batch,
)
from backend.models import (
    BatchCardResult,
    BatchGenerateRequest,
    CardDraft,
    ExportRequest,
    GenerateRequest,
    GenerateResponse,
)

# Every name imported here (generate_card, export_card, parse_and_validate,
# generate_cards_batch) becomes its own separate reference living in *this* module's
# namespace, distinct from the original in backend/llm.py, backend/anki.py, etc. The
# route functions below call these unqualified names directly (e.g. just
# `generate_card(...)`, not `llm.generate_card(...)`), so it's this module's copy of
# the reference that actually gets looked up at call time- which is exactly why
# tests/test_main.py patches "backend.main.generate_card" rather than
# "backend.llm.generate_card" to intercept those calls.
# The parenthesized `from backend.models import (...)` form is just Python's way of
# spreading a single import statement with several names across multiple lines
# without a trailing backslash on each one.


@asynccontextmanager
async def lifespan(app: FastAPI):
    # No migration tool yet (see ROADMAP.md)- this is what actually issues the
    # CREATE TABLE statements against Postgres, since init_db() itself is never
    # called anywhere else.
    init_db()
    yield


app = FastAPI(title="Anki Tool v2 Backend", lifespan=lifespan)
# This `app` object is what tests/conftest.py's `client` fixture wraps in a TestClient,
# and also what `uvicorn backend.main:app` runs directly in production- there's only
# ever one FastAPI() instance, and every route below is registered onto it via the
# @app.post(...) decorators.

# Local-only, single-user tool with no auth (see PROJECT.md non-goals) -
# permissive CORS is fine here since the frontend is served from a different
# origin (e.g. http://localhost:8080 or file://) than this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# Middleware runs on every request/response passing through the app, before/after the
# matched route function itself- CORSMiddleware specifically is what lets the browser
# actually accept these responses when frontend/index.js's `fetch()` calls are made
# from a different origin than this API; without it, the browser itself would block
# the response from ever reaching the frontend's JavaScript, regardless of what this
# backend returns.


def _resolve_level(level: str | None) -> str:
    return level or JLPT_LEVEL_DEFAULT
# Shared by both routes below so the request-level-or-env-default fallback is decided in
# exactly one place, the same way MODEL_NAMES resolves OPENROUTER_MODELS' fallback once at
# import time in backend/llm.py, rather than each route re-deriving it inline.


@app.post("/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest):
    level = _resolve_level(request.level)
    existing_word = find_word_by_kanji(request.word, level=level)
    if existing_word is not None:
        existing_card = get_card(existing_word.id)
        return GenerateResponse(
            word_id=existing_word.id,
            duplicate=True,
            card=CardDraft(
                expression=existing_word.kanji,
                reading=existing_word.reading,
                definition_ja=existing_card.definition_ja,
                nuance=existing_card.nuance,
                synonyms=existing_card.synonyms,
                antonyms=existing_card.antonyms,
                example_sentence=existing_card.example_sentence,
                jlpt_level=existing_card.jlpt_level,
            ),
        )
    # Checked before anything else, and before generate_card() is ever called- this is
    # the token-saving short-circuit. `existing_card` is rebuilt into a CardDraft here
    # (rather than exposing the ORM row directly) so the response shape is identical
    # whether `card` came from OpenRouter or from Postgres- the frontend doesn't need to
    # know which branch produced it.

    try:
        card = generate_card(request.word, level=level)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    word_id = insert_word(
        kanji=request.word, reading=card.reading, source="manual", level=level
    )
    insert_card(
        word_id=word_id,
        definition_ja=card.definition_ja,
        nuance=card.nuance,
        synonyms=card.synonyms,
        antonyms=card.antonyms,
        example_sentence=card.example_sentence,
        jlpt_level=card.jlpt_level,
    )
    # Persisted immediately- before this function returns anything to the frontend, and
    # therefore before the user has had any chance to edit a field. This is what makes
    # the cards row always equal to the model's raw output; see the write-once note on
    # Card in backend/db.py and step 3 of ARCHITECTURE.md.

    return GenerateResponse(word_id=word_id, duplicate=False, card=card)
# @app.post("/generate") registers this function as the handler for POST requests to
# that path. FastAPI parses the incoming JSON body against GenerateRequest automatically
# before this function body even runs- a request missing the "word" field, or with the
# wrong type, never reaches this code at all; FastAPI responds with its own 422 error
# first. response_model=GenerateResponse (new here- the route used to return a bare
# CardDraft) tells FastAPI the actual response shape now includes word_id/duplicate
# alongside the card itself.
# 502 ("Bad Gateway") reflects that the failure happened talking to an upstream service
# (OpenRouter), not this backend itself- the duplicate-check branch above never reaches
# this try block at all, since it never calls OpenRouter in the first place.


def _stream_batch_results(words: list[str], level: str) -> Iterator[str]:
    # One NDJSON line per yield- frontend/index.js reads this response body
    # incrementally (not as one parsed JSON document) so it can update a "3/12 done"
    # progress counter and render each carousel card as its result arrives, instead of
    # waiting for the whole batch (which can take minutes- see generate_card's 180s
    # per-attempt timeout in backend/llm.py) before showing anything.
    total = len(words)
    yield json.dumps({"total": total}) + "\n"
    # Always the very first line, before any word-specific line- lets the frontend learn
    # N up front to render "0/N" immediately, rather than inferring N from how many
    # result lines eventually arrive (which it can't know until the stream ends anyway).

    results: list[BatchCardResult | None] = [None] * total
    to_generate: list[tuple[int, str]] = []
    for i, word in enumerate(words):
        existing_word = find_word_by_kanji(word, level=level)
        if existing_word is None:
            to_generate.append((i, word))
            continue
        existing_card = get_card(existing_word.id)
        results[i] = BatchCardResult(
            word=word,
            word_id=existing_word.id,
            duplicate=True,
            card=CardDraft(
                expression=existing_word.kanji,
                reading=existing_word.reading,
                definition_ja=existing_card.definition_ja,
                nuance=existing_card.nuance,
                synonyms=existing_card.synonyms,
                antonyms=existing_card.antonyms,
                example_sentence=existing_card.example_sentence,
                jlpt_level=existing_card.jlpt_level,
            ),
        )
    # Same duplicate check /generate does for a single word (see the generate() route
    # above), just run per word up front for the whole file- these are plain Postgres
    # lookups (fast, synchronous), unlike the LLM calls below, so there's no streaming
    # concern for this part: a hit is reassembled into a BatchCardResult straight from
    # Postgres (duplicate=True, word_id already set) and placed at its original index. A
    # miss is queued in to_generate, keeping its original index so results[i] still ends
    # up correct once the loop below fills it in from generate_cards_batch().

    generated = iter(
        generate_cards_batch([word for _, word in to_generate], level=level)
    )
    # iter() is a no-op on the real generate_cards_batch() (already a generator, hence
    # already an iterator)- it's here so tests/test_main.py can keep mocking this call
    # with return_value=<a plain list>, same as before this route streamed anything, and
    # next(generated) below still works (next() requires an iterator; a bare list doesn't
    # support it).

    completed = 0
    for i, word in enumerate(words):
        if results[i] is None:
            # This index was queued in to_generate above (not a duplicate)- results and
            # to_generate were built by the same enumerate(words) loop under the same
            # is-it-a-duplicate condition, so pulling from `generated` here in this same
            # order lines each `next()` call up with the correct word, without needing to
            # track which to_generate entry this is.
            result = next(generated)
            if result.card is not None:
                word_id = insert_word(
                    kanji=result.word,
                    reading=result.card.reading,
                    source="batch",
                    level=level,
                )
                insert_card(
                    word_id=word_id,
                    definition_ja=result.card.definition_ja,
                    nuance=result.card.nuance,
                    synonyms=result.card.synonyms,
                    antonyms=result.card.antonyms,
                    example_sentence=result.card.example_sentence,
                    jlpt_level=result.card.jlpt_level,
                )
                result.word_id = word_id
            # Same insert_word/insert_card persistence /generate does for a single word. A
            # failed word (result.card is None, result.error set instead) is skipped
            # entirely- there's no card content to persist for it. Only genuinely new,
            # successful results get persisted here; a word_id lets /export later find
            # this word via get_latest_export/record_export instead of always falling
            # back to a bare addNote.
            results[i] = result
        completed += 1
        yield json.dumps(
            {"completed": completed, "total": total, "result": results[i].model_dump()}
        ) + "\n"
    # Walking `words` in file order a second time (rather than yielding duplicates and
    # generated results in the two separate passes they were computed in) is what keeps
    # the streamed line order matching the uploaded file's order- a batch that mixes an
    # already-known word with new ones would otherwise stream the (near-instant)
    # duplicate before an earlier-in-the-file word that's still mid-generation.


@app.post("/generate/batch")
def generate_batch(request: BatchGenerateRequest):
    try:
        words = parse_and_validate(request.file_content)
    except BatchValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Validation happens here, outside _stream_batch_results, specifically so a bad file
    # still gets a normal HTTPException/JSON 400 response- once StreamingResponse below
    # starts sending bytes, the status code is already committed to 200 and can't change.

    level = _resolve_level(request.level)
    return StreamingResponse(
        _stream_batch_results(words, level), media_type="application/x-ndjson"
    )
# No response_model here (unlike the plain /generate route above)- the body is a stream
# of newline-delimited JSON objects, not one document matching a single Pydantic model,
# so response_model has nothing to validate against. 400 ("Bad Request") on the
# validation-error path reflects that the problem is with what the client (frontend)
# sent- an invalid file- rather than anything going wrong on the backend or with
# OpenRouter.


@app.post("/export")
def export(request: ExportRequest):
    anki_note_id = None
    if request.word_id is not None:
        latest_export = get_latest_export(request.word_id)
        if latest_export is not None:
            anki_note_id = latest_export.anki_note_id
    # None word_id (the current batch-flow case- see ExportRequest in backend/models.py)
    # skips this entirely, so anki_note_id stays None and export_card() below does a
    # plain addNote, same as before this route knew about Postgres at all. A word_id
    # with no prior export also leaves anki_note_id None- nothing to rewrite yet, so
    # export_card() still does addNote, but see below for what happens after it succeeds.

    try:
        result_note_id = export_card(request, anki_note_id=anki_note_id)
    except AnkiConnectError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    # export_card() now returns the Anki note ID either way (see backend/anki.py)- the
    # one AnkiConnect just assigned via addNote, or the same one that was already passed
    # in via updateNoteFields. Either way it's what record_export() below needs.

    if request.word_id is not None:
        record_export(request.word_id, result_note_id)
    # Only recorded when word_id is known- there's nothing to attach an exports row to
    # otherwise. This runs on every successful export for a tracked word, not just the
    # first one: a re-export (whether or not it ended up calling updateNoteFields) still
    # appends a new exports row, per the "one row per export event" design in
    # DATABASE.md- that's what keeps get_latest_export() answering correctly for the
    # *next* re-export after this one.

    return {"status": "exported"}
# 503 ("Service Unavailable") reflects that the *downstream* service (AnkiConnect/Anki
# desktop) is the one that's unreachable or erroring, not this backend. Note the DB
# lookup above happens *before* the AnkiConnect call and the DB write happens *after*
# it succeeds- so a failed export (caught above) never reaches record_export(), and
# Postgres never claims an export happened that didn't.
