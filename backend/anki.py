# This script focuses on:
# - Resolving note types
# - Defining errors
# - Fetching Anki-relevant env vars (or using function-resolved defaults)
# - Defining card fields
# - Making POST requests to the Anki API
# - Checking existing note types, and creating a note type in the case that it is
#   inexistent.
# - Building fields to later post to AnkiConnect.
# - Card exportation: creating a new card if none exists or updating it in the case that one
#   already does.
import os

import requests

from backend.models import ExportRequest, GrammarCard, ReadingCard

ANKICONNECT_URL = os.getenv("ANKICONNECT_URL", "http://localhost:8765")
DECK_NAME = os.getenv("ANKI_DECK_NAME", "Japanese")
EXPORT_MODE = os.getenv("ANKI_EXPORT_MODE", "full")

# default_note_type returns the default note type based on the export mode.
# export_mode can either be full or basic depending on user preference.
# If full, the default note type is "Japanese Note Type"; otherwise it defaults to the basic note type.
def _default_note_type(export_mode: str) -> str:
    return "Japanese Note Type" if export_mode == "full" else "Basic"

# NOTE_TYPE is either a user-supplied ANKI_NOTE_TYPE (any name) or, if that env var isn't set,
# whatever _default_note_type returns for the current EXPORT_MODE ("Japanese Note Type" for
# full, "Basic" for basic).
NOTE_TYPE = os.getenv("ANKI_NOTE_TYPE", _default_note_type(EXPORT_MODE))


class AnkiConnectError(Exception):
    """Raised when AnkiConnect is unreachable or returns an error."""

# Defines a list specifying the fields for the full mode note type.
# In Python, a list differs from an array in the sense that the contents can be of different types,
# while an array is typically homogeneous. (Assuming arrays as implemented in the C language.)
# Memory efficiency depends on what's stored: arrays are more compact for small primitives
# (no per-element boxing overhead), while lists' pointer indirection avoids needing fixed-size
# slots for large or variable-sized objects. Neither case really applies to the short strings
# FULL_MODE_FIELDS holds.
FULL_MODE_FIELDS = [
    "Expression", "Reading", "Definition", "Nuance",
    "Synonyms", "Antonyms", "Example", "Jlpt",
]

# os.getenv(key, default=None) is the generic syntax for the following implemented function.
GRAMMAR_NOTE_TYPE = os.getenv(
    "ANKI_GRAMMAR_NOTE_TYPE",
    "Japanese Grammar Note Type" if EXPORT_MODE == "full" else "Basic",
)

# A Reading card is just a card that has a set topic and passage to read relating to the
# aforementioned subject matter, paired with a question and answer, vocab notes, and a
# JLPT level estimate- see models.py.
READING_NOTE_TYPE = os.getenv(
    "ANKI_READING_NOTE_TYPE",
    "Japanese Reading Note Type" if EXPORT_MODE == "full" else "Basic",
)

# The fields listed here must correspond to the mapping in _build_grammar_fields/_build_reading_fields-
# names differ from the models.py card fields themselves (e.g. Jlpt vs jlpt_level).
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
        # The request payload must be a JSON object containing the action, version and parameters.
        # That is the format that the AnkiConnect API expects.
        response.raise_for_status()
        # A built-in method used to automatically raise an exception if an HTTP request fails.
    except requests.RequestException as exc:
        raise AnkiConnectError(
            f"Could not reach AnkiConnect at {ANKICONNECT_URL}: {exc}"
        ) from exc
        # In Python, the raise Exception from e syntax is
        # used for exception chaining.
        # In Python, a stack trace allows developers to trace the
        # sequence of function calls that led to an error or exception.
        # `raise exception from e` syntax allows errors to be linked together,
        # providing context about the original exception that caused the current
        # one.

    data = response.json() # Get the JSON response from the AnkiConnect
    # API. The response is expected, in the case of request.post() method
    # invocation, to be a JSON object containing the result of the HTTP request.
    if data.get("error"):
        # data.get("error") is truthy only if "error" is present with a non-null/non-empty
        # value (AnkiConnect sends "error": null on success, which is falsy).
        # If truthy, it raises an error. Otherwise, the data is safely returned.
        raise AnkiConnectError(data["error"])
    return data

# _ensure_note_type checks if a note type exists in AnkiConnect,
# and creates it if it doesn't. The front_field parameter
# specifies which field should be displayed on the front of the card.
def _ensure_note_type(note_type: str, fields: list[str], front_field: str) -> None:
    # Calls AnkiConnect's modelNames action (no params)
    # to get the list of every note
    # type name currently defined in the user's Anki collection.
    # data becomes the parsed JSON response, e.g. {"result": ["Basic",
    # "Japanese Note Type", ...], "error": null}.
    # The next line (data["result"]) checks whether the target note
    # type already exists, to decide if createModel is needed.
    data = _post_to_ankiconnect("modelNames", {})
    if note_type in data["result"]:
        return

    back_fields = "<br>".join(f"{{{{{field}}}}}" for field in fields if field != front_field)
    # Builds the HTML for the back of the card template: every field except
    # front_field, joined by <br>. f"{{{{{field}}}}}" -> Anki's {{FieldName}}
    # syntax (quadruple braces
    # because {{ and }} are escaped literal braces in an f-string, with {field} in between).
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

# If EXPORT_MODE is not set to either basic or full,
# _build_fields raises a ValueError.
# Otherwise, it builds a dictionary of fields according to the type.
def _build_fields(card: ExportRequest) -> dict:
    # A dict behaves like a dynamic object whose properties (keys) can be
    # added, deleted, or updated at runtime without modifying a
    # class blueprint.
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

# anki_note_id could be an integer rather than None in the case that
# the call to the Postgres database in main.py returns a valid
# note ID for the export.
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

# _add_note_checked adds a note to AnkiConnect and returns a tuple
# containing the note ID (or None if it was not added) and a 
# boolean indicating whether the note was added successfully.
# The model_name parameter specifies the note type (e.g., "Japanese
# Note Type", or the reading note type or the grammar note type).
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
