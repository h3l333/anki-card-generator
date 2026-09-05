import json

from collections.abc import Iterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend.anki import (
    AnkiConnectError,
    export_card,
    export_dataset_vocab_card,
    export_grammar_card,
    export_reading_card,
)
from backend.batch import BatchValidationError, parse_and_validate
from backend import datasets
from backend.datasets import DatasetNotFoundError, DatasetValidationError
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
    generate_dataset_batch,
)
from backend.models import (
    BatchCardResult,
    BatchGenerateRequest,
    CardDraft,
    DatasetCardResult,
    DatasetGenerateRequest,
    ExportRequest,
    GenerateRequest,
    GrammarCard,
    ReadingCard,
    card_draft_to_export_request,
)



@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    llm._EXECUTOR.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Anki Tool v2 Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_level(level: str | None) -> str:
    return level or JLPT_LEVEL_DEFAULT


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


def _stream_generate_result(word: str, level: str, mode: str) -> Iterator[str]:
    for event in generate_card_with_events(word, level, mode=mode):
        if event["event"] == "result":
            try:
                card = CardDraft(**event["card"])
                word_id = _persist_generated_card(word, level, "manual", card)
            except Exception as exc:
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

    return StreamingResponse(
        _stream_generate_result(request.word, level, request.mode), media_type="application/x-ndjson"
    )


def _stream_batch_results(words: list[str], level: str, mode: str) -> Iterator[str]:
    total = len(words)
    yield json.dumps({"total": total}) + "\n"

    results: list[BatchCardResult | None] = [None] * total
    to_generate: list[tuple[int, str]] = []
    for i, word in enumerate(words):
        existing = _lookup_existing_card(word, level)
        if existing is None:
            to_generate.append((i, word))
            continue
        word_id, card = existing
        results[i] = BatchCardResult(word=word, word_id=word_id, duplicate=True, card=card)

    generated = iter(
        generate_cards_batch([word for _, word in to_generate], level=level, mode=mode)
    )

    completed = 0
    for i, word in enumerate(words):
        if results[i] is None:
            item = next(generated)
            while not isinstance(item, BatchCardResult):
                yield json.dumps(item) + "\n"
                item = next(generated)
            result = item
            if result.card is not None:
                result.word_id = _persist_generated_card(result.word, level, "batch", result.card)
            results[i] = result
        completed += 1
        yield json.dumps(
            {"completed": completed, "total": total, "result": results[i].model_dump()}
        ) + "\n"


@app.post("/generate/batch")
def generate_batch(request: BatchGenerateRequest):
    try:
        words = parse_and_validate(request.file_content)
    except BatchValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    level = _resolve_level(request.level)
    return StreamingResponse(
        _stream_batch_results(words, level, request.mode), media_type="application/x-ndjson"
    )


def _stream_export_only(word_id: int, card: CardDraft, duplicate: bool) -> Iterator[str]:
    export_request = card_draft_to_export_request(card, word_id=word_id)
    latest_export = get_latest_export(word_id)
    anki_note_id = latest_export.anki_note_id if latest_export is not None else None
    try:
        note_id = export_card(export_request, anki_note_id=anki_note_id)
    except AnkiConnectError as exc:
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


@app.post("/export")
def export(request: ExportRequest):
    anki_note_id = None
    if request.word_id is not None:
        latest_export = get_latest_export(request.word_id)
        if latest_export is not None:
            anki_note_id = latest_export.anki_note_id

    try:
        result_note_id = export_card(request, anki_note_id=anki_note_id)
    except AnkiConnectError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if request.word_id is not None:
        record_export(request.word_id, result_note_id)

    return {"status": "exported"}




def _stream_dataset_results(
    items: list[dict], section: str, level: str, mode: str
) -> Iterator[str]:
    total = len(items)
    yield json.dumps({"total": total, "section": section}) + "\n"
    completed = 0
    for event in generate_dataset_batch(items, section, level=level, mode=mode):
        if not isinstance(event, DatasetCardResult):
            yield json.dumps(event) + "\n"
            continue
        completed += 1
        yield json.dumps(
            {"completed": completed, "total": total, "result": event.model_dump()}
        ) + "\n"


@app.post("/generate/dataset")
def generate_dataset(request: DatasetGenerateRequest):
    level = _resolve_level(request.level)
    try:
        items = datasets.load_section(level, request.section)
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatasetValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return StreamingResponse(
        _stream_dataset_results(items, request.section, level, request.mode),
        media_type="application/x-ndjson",
    )


@app.post("/export/grammar")
def export_grammar(card: GrammarCard):
    try:
        note_id, created = export_grammar_card(card, card.tags)
    except AnkiConnectError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "exported" if created else "duplicate", "note_id": note_id}


@app.post("/export/reading")
def export_reading(card: ReadingCard):
    try:
        note_id, created = export_reading_card(card, card.tags)
    except AnkiConnectError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "exported" if created else "duplicate", "note_id": note_id}


@app.post("/export/dataset-vocab")
def export_dataset_vocab(request: ExportRequest):
    try:
        note_id, created = export_dataset_vocab_card(request, request.tags)
    except AnkiConnectError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "exported" if created else "duplicate", "note_id": note_id}
