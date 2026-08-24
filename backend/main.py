# 3 FastAPI routes
import json
# Used by _stream_generate_result and _stream_batch_results below- each NDJSON line
# they yield is a plain dict serialized by hand via json.dumps, not a Pydantic model,
# since StreamingResponse just wants raw bytes/str chunks rather than something FastAPI
# can validate against a response_model.

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
from backend import llm
from backend.llm import (
    JLPT_LEVEL_DEFAULT,
    generate_card_with_events,
    generate_cards_batch,
)
from backend.models import (
    BatchCardResult,
    BatchGenerateRequest,
    CardDraft,
    ExportRequest,
    GenerateRequest,
    card_draft_to_export_request,
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
    # `yield` hands control back to FastAPI to run the app.
    # `@asynccontextmanager` requires a generator (a `yield` somewhere in the body)-
    # swapping it for `return` would stop this from being a generator function at all,
    # so FastAPI's `async with lifespan(app):` would fail at startup instead of just
    # skipping cleanup.
    yield
    llm._EXECUTOR.shutdown(wait=False, cancel_futures=True)
    # Without this, shutdown would hang on ThreadPoolExecutor's default atexit join.
    # cancel_futures=True only drops futures that haven't started running yet- a
    # generation already mid-`requests.post` can't be forcibly killed (Python threads
    # aren't preemptible), so shutdown during an in-flight call still waits it out.


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
    allow_origins=["*"], # Allows requests from any origin.
    allow_methods=["*"], # Permits all HTTP methods.
    allow_headers=["*"], # Accepts all HTTP request headers.
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


def _lookup_existing_card(word: str, level: str) -> tuple[int, CardDraft] | None:
    existing_word = find_word_by_kanji(word, level=level)
    if existing_word is None:
        return None
    existing_card = get_card(existing_word.id)
    card = CardDraft(
        expression=existing_word.kanji,
        reading=existing_word.reading,
        definition_ja=existing_card.definition_ja,
        nuance=existing_card.nuance,
        synonyms=existing_card.synonyms,
        antonyms=existing_card.antonyms,
        example_sentence=existing_card.example_sentence,
        jlpt_level=existing_card.jlpt_level,
    )
    return existing_word.id, card
# Shared duplicate-check-and-rebuild step: a Postgres hit is reassembled into a CardDraft so
# its shape is identical whether `card` came from OpenRouter or from Postgres, the same
# reasoning generate() below originally had inline. Used by generate(), _stream_batch_results()
# and _stream_generate_export_result() so this rebuild only lives in one place.


def _persist_generated_card(word: str, level: str, source: str, card: CardDraft) -> int:
    word_id = insert_word(kanji=word, reading=card.reading, source=source, level=level)
    insert_card(
        word_id=word_id,
        definition_ja=card.definition_ja,
        nuance=card.nuance,
        synonyms=card.synonyms,
        antonyms=card.antonyms,
        example_sentence=card.example_sentence,
        jlpt_level=card.jlpt_level,
    )
    return word_id
# Shared insert_word/insert_card pair for a freshly-generated (non-duplicate) card- `source`
# distinguishes which flow produced it ("manual" for /generate, "batch" for /generate/batch,
# "extension" for /generate/export), same words table, no schema change.


def _stream_generate_result(word: str, level: str, mode: str) -> Iterator[str]:
    # Mirrors _stream_batch_results below but for a single word: passes heartbeat/retry
    # events straight through as NDJSON lines, then on the terminal event either
    # persists the newly-generated card (success) or reports why it failed (error)-
    # both as one final NDJSON line, since the HTTP status is already committed to 200
    # by the time any of this runs (see generate() below).
    for event in generate_card_with_events(word, level, mode=mode):
        if event["event"] == "result":
            try:
                card = CardDraft(**event["card"])
                word_id = _persist_generated_card(word, level, "manual", card)
            except Exception as exc:
                # A DB failure this late can no longer become an HTTPException (bytes
                # are already flushed)- it has to resolve to its own error line instead
                # of raising out of this generator, which Starlette would otherwise just
                # turn into a truncated response the client can't distinguish from a
                # network blip.
                yield json.dumps({"event": "error", "detail": f"failed to save card: {exc}"}) + "\n"
                return
            yield json.dumps(
                {"event": "result", "duplicate": False, "word_id": word_id, "card": card.model_dump()}
            ) + "\n"
            return
        yield json.dumps(event) + "\n"


@app.post("/generate")
def generate(request: GenerateRequest):
    level = _resolve_level(request.level)
    existing = _lookup_existing_card(request.word, level)
    if existing is not None:
        word_id, card = existing
        line = json.dumps(
            {"event": "result", "duplicate": True, "word_id": word_id, "card": card.model_dump()}
        ) + "\n"
        return StreamingResponse(iter([line]), media_type="application/x-ndjson")
    # Checked before anything else, and before generate_card_with_events() is ever
    # called- this is the token-saving short-circuit, and stays a single synchronous
    # line (no thread pool, no polling) since there's no OpenRouter call to report
    # progress on. `existing_card` is rebuilt into a CardDraft here (rather than
    # exposing the ORM row directly) so the payload shape is identical whether `card`
    # came from OpenRouter or from Postgres- the frontend doesn't need to know which
    # branch produced it.

    return StreamingResponse(
        _stream_generate_result(request.word, level, request.mode), media_type="application/x-ndjson"
    )
# @app.post("/generate") registers this function as the handler for POST requests to
# that path. FastAPI parses the incoming JSON body against GenerateRequest automatically
# before this function body even runs- a request missing the "word" field, or with the
# wrong type, never reaches this code at all; FastAPI responds with its own 422 error
# first. The response body is now a stream of newline-delimited JSON event lines (see
# _stream_generate_result and the event schema comment on _stream_batch_results below),
# not a single GenerateResponse document- this is what lets the frontend show live
# progress (heartbeat/retry) instead of just waiting on one blocking response. A
# generation failure (formerly a 502) is now the stream's terminal
# {"event": "error", "detail": ...} line instead of an HTTP error status, since the
# status code is already committed to 200 by the time StreamingResponse starts sending
# bytes.


def _stream_batch_results(words: list[str], level: str, mode: str) -> Iterator[str]:
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
        existing = _lookup_existing_card(word, level)
        if existing is None:
            to_generate.append((i, word))
            continue
        word_id, card = existing
        results[i] = BatchCardResult(word=word, word_id=word_id, duplicate=True, card=card)
    # Same duplicate check /generate does for a single word (see the generate() route
    # above), just run per word up front for the whole file- these are plain Postgres
    # lookups (fast, synchronous), unlike the LLM calls below, so there's no streaming
    # concern for this part: a hit is reassembled into a BatchCardResult straight from
    # Postgres (duplicate=True, word_id already set) and placed at its original index. A
    # miss is queued in to_generate, keeping its original index so results[i] still ends
    # up correct once the loop below fills it in from generate_cards_batch().

    generated = iter(
        generate_cards_batch([word for _, word in to_generate], level=level, mode=mode)
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
            item = next(generated)
            while not isinstance(item, BatchCardResult):
                # A heartbeat/retry progress dict (see generate_cards_batch/
                # generate_card_with_events in backend/llm.py) for this word's still-
                # in-flight generation- passed straight through as its own NDJSON line
                # so the frontend can show it's not just the LLM call finishing, and
                # keep pulling until the word's terminal BatchCardResult arrives.
                yield json.dumps(item) + "\n"
                item = next(generated)
            result = item
            if result.card is not None:
                result.word_id = _persist_generated_card(result.word, level, "batch", result.card)
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
        _stream_batch_results(words, level, request.mode), media_type="application/x-ndjson"
    )
# No response_model here (unlike the plain /generate route above)- the body is a stream
# of newline-delimited JSON objects, not one document matching a single Pydantic model,
# so response_model has nothing to validate against. 400 ("Bad Request") on the
# validation-error path reflects that the problem is with what the client (frontend)
# sent- an invalid file- rather than anything going wrong on the backend or with
# OpenRouter.


def _stream_export_only(word_id: int, card: CardDraft, duplicate: bool) -> Iterator[str]:
    export_request = card_draft_to_export_request(card, word_id=word_id)
    latest_export = get_latest_export(word_id)
    anki_note_id = latest_export.anki_note_id if latest_export is not None else None
    try:
        note_id = export_card(export_request, anki_note_id=anki_note_id)
    except AnkiConnectError as exc:
        # Generation (or the Postgres duplicate lookup) already succeeded and the word is
        # already persisted- only the AnkiConnect call failed, so this is recoverable: the
        # extension can tell the user to open the web frontend and generate the same word,
        # which will hit the duplicate short-circuit and let them export manually from there.
        yield json.dumps({
            "event": "error",
            "stage": "export",
            "detail": str(exc),
            "word_id": word_id,
            "duplicate": duplicate,
            "card": card.model_dump(),
        }) + "\n"
        return
    record_export(word_id, note_id)
    yield json.dumps({
        "event": "exported",
        "duplicate": duplicate,
        "word_id": word_id,
        "anki_note_id": note_id,
        "card": card.model_dump(),
    }) + "\n"


def _stream_generate_export_result(word: str, level: str, mode: str) -> Iterator[str]:
    # Mirrors _stream_generate_result above, but the terminal event is "generated and
    # exported" rather than just "generated"- there's no frontend review step for this
    # route to hand a reviewed card back to, so the card goes straight to AnkiConnect via
    # _stream_export_only as soon as it's available (freshly generated or a Postgres hit).
    existing = _lookup_existing_card(word, level)
    if existing is not None:
        word_id, card = existing
        yield from _stream_export_only(word_id, card, duplicate=True)
        return

    for event in generate_card_with_events(word, level, mode=mode):
        if event["event"] == "error":
            yield json.dumps({"event": "error", "stage": "generate", "detail": event["detail"]}) + "\n"
            return
        if event["event"] != "result":
            yield json.dumps(event) + "\n"
            continue
        try:
            card = CardDraft(**event["card"])
            word_id = _persist_generated_card(word, level, "extension", card)
        except Exception as exc:
            yield json.dumps({"event": "error", "stage": "generate", "detail": f"failed to save card: {exc}"}) + "\n"
            return
        yield from _stream_export_only(word_id, card, duplicate=False)
        return


@app.post("/generate/export")
def generate_and_export(request: GenerateRequest):
    level = _resolve_level(request.level)
    return StreamingResponse(
        _stream_generate_export_result(request.word, level, request.mode),
        media_type="application/x-ndjson",
    )
# Combined generate+export for the Chrome extension (extension/background.js)- it has no
# review/edit UI, so it skips the generate-then-separately-POST-/export round trip and gets
# one endpoint that does both server-side. `stage` on an "error" event tells the caller
# whether generation itself failed ("generate"- nothing new persisted) or only the AnkiConnect
# push failed ("export"- the word is already saved in Postgres, so it's recoverable via the
# web frontend's ordinary duplicate-word flow). A successful terminal event is named
# "exported", not "result" like plain /generate's, specifically so a client can't confuse "the
# card was generated" with "the card actually reached Anki".


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
