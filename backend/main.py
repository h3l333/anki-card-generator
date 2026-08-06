# 3 FastAPI routes
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.anki import AnkiConnectError, export_card
from backend.batch import BatchValidationError, parse_and_validate
from backend.db import (
    find_word_by_kanji,
    get_card,
    get_latest_export,
    insert_card,
    insert_word,
    record_export,
)
from backend.llm import LLMError, generate_card, generate_cards_batch
from backend.models import (
    BatchGenerateRequest,
    BatchGenerateResponse,
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

app = FastAPI(title="Anki Tool v2 Backend")
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


@app.post("/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest):
    existing_word = find_word_by_kanji(request.word)
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
        card = generate_card(request.word)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    word_id = insert_word(kanji=request.word, reading=card.reading, source="manual")
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


@app.post("/generate/batch", response_model=BatchGenerateResponse)
def generate_batch(request: BatchGenerateRequest):
    try:
        words = parse_and_validate(request.file_content)
    except BatchValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return BatchGenerateResponse(results=generate_cards_batch(words))
# response_model=BatchGenerateResponse (unlike the plain /generate route above) tells
# FastAPI explicitly what shape this route's successful response should be- used here
# to generate accurate OpenAPI docs for a route whose return type isn't otherwise
# obvious from the function signature alone. 400 ("Bad Request") reflects that the
# problem is with what the client (frontend) sent- an invalid file- rather than
# anything going wrong on the backend or with OpenRouter.


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
