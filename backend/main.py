from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.anki import AnkiConnectError, export_card
from backend.llm import LLMError, generate_card
from backend.models import ExportRequest, GenerateRequest

app = FastAPI(title="Anki Tool v2 Backend")

# Local-only, single-user tool with no auth (see PROJECT.md non-goals) -
# permissive CORS is fine here since the frontend is served from a different
# origin (e.g. http://localhost:8080 or file://) than this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/generate")
def generate(request: GenerateRequest):
    try:
        return generate_card(request.word)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/export")
def export(request: ExportRequest):
    try:
        export_card(request)
    except AnkiConnectError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "exported"}
