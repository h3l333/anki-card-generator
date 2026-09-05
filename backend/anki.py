import os

import requests

from backend.models import ExportRequest, GrammarCard, ReadingCard

ANKICONNECT_URL = os.getenv("ANKICONNECT_URL", "http://localhost:8765")
DECK_NAME = os.getenv("ANKI_DECK_NAME", "Japanese")
EXPORT_MODE = os.getenv("ANKI_EXPORT_MODE", "full")

def _default_note_type(export_mode: str) -> str:
    return "Japanese Note Type" if export_mode == "full" else "Basic"


NOTE_TYPE = os.getenv("ANKI_NOTE_TYPE", _default_note_type(EXPORT_MODE))


class AnkiConnectError(Exception):
    """Raised when AnkiConnect is unreachable or returns an error."""


FULL_MODE_FIELDS = [
    "Expression", "Reading", "Definition", "Nuance",
    "Synonyms", "Antonyms", "Example", "Jlpt",
]

GRAMMAR_NOTE_TYPE = os.getenv(
    "ANKI_GRAMMAR_NOTE_TYPE",
    "Japanese Grammar Note Type" if EXPORT_MODE == "full" else "Basic",
)
READING_NOTE_TYPE = os.getenv(
    "ANKI_READING_NOTE_TYPE",
    "Japanese Reading Note Type" if EXPORT_MODE == "full" else "Basic",
)

GRAMMAR_FULL_MODE_FIELDS = [
    "Pattern", "Connection", "Meaning", "Nuance",
    "SimilarPatterns", "Example", "Jlpt",
]
READING_FULL_MODE_FIELDS = [
    "Topic", "Passage", "Question", "Answer", "VocabNotes", "Jlpt",
]


def _post_to_ankiconnect(action: str, params: dict) -> dict:
    try:
        response = requests.post(
            ANKICONNECT_URL,
            json={"action": action, "version": 6, "params": params},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AnkiConnectError(
            f"Could not reach AnkiConnect at {ANKICONNECT_URL}: {exc}"
        ) from exc

    data = response.json()
    if data.get("error"):
        raise AnkiConnectError(data["error"])
    return data


def _ensure_note_type(note_type: str, fields: list[str], front_field: str) -> None:
    data = _post_to_ankiconnect("modelNames", {})
    if note_type in data["result"]:
        return

    back_fields = "<br>".join(f"{{{{{field}}}}}" for field in fields if field != front_field)
    _post_to_ankiconnect(
        "createModel",
        {
            "modelName": note_type,
            "inOrderFields": fields,
            "css": ".card { font-family: sans-serif; font-size: 20px; text-align: center; }",
            "cardTemplates": [
                {
                    "Name": "Card 1",
                    "Front": f"{{{{{front_field}}}}}",
                    "Back": f"{{{{FrontSide}}}}<hr id=answer>{back_fields}",
                }
            ],
        },
    )


def _build_fields(card: ExportRequest) -> dict:
    if EXPORT_MODE == "full":
        return {
            "Expression": card.expression,
            "Reading": card.reading,
            "Definition": card.definition,
            "Nuance": card.nuance,
            "Synonyms": card.synonyms,
            "Antonyms": card.antonyms,
            "Example": card.example,
            "Jlpt": card.jlpt,
        }

    if EXPORT_MODE != "basic":
        raise ValueError(
            f"Invalid ANKI_EXPORT_MODE: {EXPORT_MODE!r} (expected 'basic' or 'full')"
        )

    front = f"{card.expression}"
    back = (
        f"<b>Reading:</b> {card.reading}<br>"
        f"<b>Definition:</b> {card.definition}<br>"
        f"<b>Nuance:</b> {card.nuance}<br>"
        f"<b>Synonyms:</b> {card.synonyms}<br>"
        f"<b>Antonyms:</b> {card.antonyms}<br>"
        f"<b>Example:</b> {card.example}<br>"
        f"<b>JLPT:</b> {card.jlpt}"
    )
    return {"Front": front, "Back": back}


def export_card(card: ExportRequest, anki_note_id: int | None = None) -> int:
    if EXPORT_MODE == "full":
        _ensure_note_type(NOTE_TYPE, FULL_MODE_FIELDS, "Expression")

    if anki_note_id is None:
        action = "addNote"
        params = {
            "note": {
                "deckName": DECK_NAME,
                "modelName": NOTE_TYPE,
                "fields": _build_fields(card),
                "options": {"allowDuplicate": False},
                "tags": ["anki-tool-v2", *card.tags],
            }
        }
    else:
        action = "updateNoteFields"
        params = {
            "note": {
                "id": anki_note_id,
                "fields": _build_fields(card),
            }
        }

    data = _post_to_ankiconnect(action, params)

    return data["result"] if anki_note_id is None else anki_note_id




def _build_grammar_fields(card: GrammarCard) -> dict:
    if EXPORT_MODE == "full":
        return {
            "Pattern": card.pattern,
            "Connection": card.connection,
            "Meaning": card.meaning,
            "Nuance": card.nuance,
            "SimilarPatterns": card.similar_patterns,
            "Example": card.example_sentence,
            "Jlpt": card.jlpt_level,
        }

    if EXPORT_MODE != "basic":
        raise ValueError(
            f"Invalid ANKI_EXPORT_MODE: {EXPORT_MODE!r} (expected 'basic' or 'full')"
        )

    front = f"{card.pattern}"
    back = (
        f"<b>Connection:</b> {card.connection}<br>"
        f"<b>Meaning:</b> {card.meaning}<br>"
        f"<b>Nuance:</b> {card.nuance}<br>"
        f"<b>Similar patterns:</b> {card.similar_patterns}<br>"
        f"<b>Example:</b> {card.example_sentence}<br>"
        f"<b>JLPT:</b> {card.jlpt_level}"
    )
    return {"Front": front, "Back": back}


def _build_reading_fields(card: ReadingCard) -> dict:
    if EXPORT_MODE == "full":
        return {
            "Topic": card.topic,
            "Passage": card.passage,
            "Question": card.question,
            "Answer": card.answer,
            "VocabNotes": card.vocab_notes,
            "Jlpt": card.jlpt_level,
        }

    if EXPORT_MODE != "basic":
        raise ValueError(
            f"Invalid ANKI_EXPORT_MODE: {EXPORT_MODE!r} (expected 'basic' or 'full')"
        )

    front = f"{card.topic}"
    back = (
        f"<b>Passage:</b> {card.passage}<br>"
        f"<b>Question:</b> {card.question}<br>"
        f"<b>Answer:</b> {card.answer}<br>"
        f"<b>Vocab notes:</b> {card.vocab_notes}<br>"
        f"<b>JLPT:</b> {card.jlpt_level}"
    )
    return {"Front": front, "Back": back}


def _add_note_checked(
    model_name: str, fields: dict, tags: list[str] | None
) -> tuple[int | None, bool]:
    data = _post_to_ankiconnect(
        "addNote",
        {
            "note": {
                "deckName": DECK_NAME,
                "modelName": model_name,
                "fields": fields,
                "options": {"allowDuplicate": False},
                "tags": ["anki-tool-v2", *(tags or [])],
            }
        },
    )
    note_id = data["result"]
    return (note_id, True) if note_id is not None else (None, False)


def export_grammar_card(card: GrammarCard, tags: list[str] | None = None) -> tuple[int | None, bool]:
    if EXPORT_MODE == "full":
        _ensure_note_type(GRAMMAR_NOTE_TYPE, GRAMMAR_FULL_MODE_FIELDS, "Pattern")
    return _add_note_checked(GRAMMAR_NOTE_TYPE, _build_grammar_fields(card), tags)


def export_reading_card(card: ReadingCard, tags: list[str] | None = None) -> tuple[int | None, bool]:
    if EXPORT_MODE == "full":
        _ensure_note_type(READING_NOTE_TYPE, READING_FULL_MODE_FIELDS, "Topic")
    return _add_note_checked(READING_NOTE_TYPE, _build_reading_fields(card), tags)


def export_dataset_vocab_card(
    card: ExportRequest, tags: list[str] | None = None
) -> tuple[int | None, bool]:
    if EXPORT_MODE == "full":
        _ensure_note_type(NOTE_TYPE, FULL_MODE_FIELDS, "Expression")
    return _add_note_checked(NOTE_TYPE, _build_fields(card), tags)
