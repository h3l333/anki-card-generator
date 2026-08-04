# 3 FastAPI routes
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.anki import AnkiConnectError, export_card
from backend.batch import BatchValidationError, parse_and_validate
from backend.llm import LLMError, generate_card, generate_cards_batch
from backend.models import (
    BatchGenerateRequest,
    BatchGenerateResponse,
    ExportRequest,
    GenerateRequest,
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


@app.post("/generate")
def generate(request: GenerateRequest):
    try:
        return generate_card(request.word)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
# @app.post("/generate") registers this function as the handler for POST requests to
# that path. FastAPI parses the incoming JSON body against GenerateRequest automatically
# before this function body even runs- a request missing the "word" field, or with the
# wrong type, never reaches this code at all; FastAPI responds with its own 422 error
# first. Returning a CardDraft instance (from generate_card) directly here works because
# FastAPI knows how to serialize any Pydantic BaseModel into a JSON response body on its
# own, without this function needing to call anything like .model_dump() itself.
# 502 ("Bad Gateway") reflects that the failure happened talking to an upstream service
# (OpenRouter), not this backend itself.


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
    try:
        export_card(request)
    except AnkiConnectError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "exported"}
# export_card() itself returns None (see backend/anki.py)- it either succeeds silently
# or raises, so the actual success response body ({"status": "exported"}) is built here
# in the route function, not returned from export_card(). 503 ("Service Unavailable")
# reflects that the *downstream* service (AnkiConnect/Anki desktop) is the one that's
# unreachable or erroring, not this backend.
