import os
# os.getenv reads environment variables- used below so AnkiConnect's URL, deck name,
# and note type can all be overridden without touching this file (see README Configuration).

import requests
# The same `requests` library backend/llm.py uses for OpenRouter- here it's the HTTP
# client used to talk to AnkiConnect instead.

from backend.models import ExportRequest

ANKICONNECT_URL = os.getenv("ANKICONNECT_URL", "http://localhost:8765")
DECK_NAME = os.getenv("ANKI_DECK_NAME", "Japanese")
EXPORT_MODE = os.getenv("ANKI_EXPORT_MODE", "full")
# "full" (default) sends each field individually for a custom note type with matching
# field names, auto-created via createModel if missing (see _ensure_full_mode_note_type
# below)- zero setup burden now that that auto-create exists, and it's the richer export
# (all eight fields land in Anki, not just two). "basic" folds all eight fields into
# Front/Back instead, for Anki's stock "Basic" note type (see README Configuration). Any
# other value is a config mistake, not a mode to silently fall back from- _build_fields
# raises on it below.

def _default_note_type(export_mode: str) -> str:
    # Only ANKI_NOTE_TYPE itself overrides the result of this- the default depends on
    # export_mode so "full" mode works with zero note-type config too: "Japanese Note
    # Type" doesn't collide with Anki's stock "Basic", so _ensure_full_mode_note_type
    # (below) auto-creates it via createModel on first export instead of the user having
    # to pick and set a name first.
    return "Japanese Note Type" if export_mode == "full" else "Basic"


NOTE_TYPE = os.getenv("ANKI_NOTE_TYPE", _default_note_type(EXPORT_MODE))
# os.getenv("NAME", default) returns the environment variable's value if it's set, or
# the given default otherwise- so these constants work out of the box for a fresh install
# (default Anki deck/note type, default AnkiConnect port) while still being overridable
# per-user without any code change.


class AnkiConnectError(Exception):
    """Raised when AnkiConnect is unreachable or returns an error."""
    # backend/main.py's /export route catches this specifically and turns it into an
    # HTTP 503 response- see the two distinct raise sites in export_card() below for
    # the two different situations this same exception type covers.


FULL_MODE_FIELDS = [
    "Expression", "Reading", "Definition", "Nuance",
    "Synonyms", "Antonyms", "Example", "Jlpt",
]
# Same field names _build_fields uses for "full" mode below- pulled out to a module-level
# constant so _ensure_full_mode_note_type can pass them to AnkiConnect's createModel
# without repeating the list a second time.


def _post_to_ankiconnect(action: str, params: dict) -> dict:
    # Every AnkiConnect call in this module (modelNames, createModel, addNote,
    # updateNoteFields) shares the same request envelope, transport-error handling, and
    # logical-error handling- centralized here instead of repeated at each call site.
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


def _ensure_full_mode_note_type() -> None:
    # "full" mode targets a custom note type (ANKI_NOTE_TYPE) that AnkiConnect's
    # addNote/updateNoteFields will happily fail on with a not-very-actionable error if it
    # doesn't exist yet, or doesn't have the fields _build_fields tries to fill. Creating it
    # up front via AnkiConnect's own createModel action lets "full" mode work against a
    # stock Anki profile without the user having to hand-build the note type first.
    data = _post_to_ankiconnect("modelNames", {})
    if NOTE_TYPE in data["result"]:
        # Already exists- leave it alone. createModel has no "update" mode, and this
        # should never silently overwrite a note type the user may have customized
        # (templates, styling, extra fields beyond the eight expected here).
        return

    back_fields = "<br>".join(f"{{{{{field}}}}}" for field in FULL_MODE_FIELDS[1:])
    _post_to_ankiconnect(
        "createModel",
        {
            "modelName": NOTE_TYPE,
            "inOrderFields": FULL_MODE_FIELDS,
            "css": ".card { font-family: sans-serif; font-size: 20px; text-align: center; }",
            "cardTemplates": [
                {
                    "Name": "Card 1",
                    "Front": "{{Expression}}",
                    "Back": f"{{{{FrontSide}}}}<hr id=answer>{back_fields}",
                }
            ],
        },
    )


def _build_fields(card: ExportRequest) -> dict:
    # Anki renders card fields as HTML, not plain text- <b> and <br> below are actual
    # HTML tags, not a formatting convention specific to this project. That's also why
    # this function returns a plain dict rather than an ExportRequest: AnkiConnect's
    # own API expects note fields as a {"FieldName": "HTML string"} mapping, keyed by
    # the exact field names the target note type defines.
    if EXPORT_MODE == "full":
        # One field per note field, for a custom note type whose field names match
        # these exactly (see README Configuration)- no folding needed since each piece
        # of data gets its own field instead of being concatenated into Front/Back.
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

    # "Basic" only has Front/Back- fold the eight card fields into those two
    # until a custom Japanese note type exists in Anki (see README Configuration).
    # "Folding" in this context means to combine, flatten or merge multiple pieces of data into fewer containers.
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
        # Only "full" mode needs this- "basic" mode targets Anki's stock "Basic" note
        # type, which always exists, so there's nothing to create.
        _ensure_full_mode_note_type()

    if anki_note_id is None:
        action = "addNote"
        params = {
            "note": {
                "deckName": DECK_NAME,
                "modelName": NOTE_TYPE,
                "fields": _build_fields(card),
                "options": {"allowDuplicate": False},
                "tags": ["anki-tool-v2"],
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
    # anki_note_id is None- the normal case, and the only case before this parameter
    # existed- means there's no existing Anki note to target, so this builds a fresh
    # addNote call exactly as before. A caller (backend/main.py's /export route) that
    # already knows this word has an export history passes the note ID AnkiConnect
    # assigned last time instead, which switches this to updateNoteFields- AnkiConnect's
    # own action for overwriting an existing note's fields in place. Note the shape
    # difference: updateNoteFields only takes {id, fields}, not deckName/modelName/
    # options/tags- those describe where/how to *create* a note, which doesn't apply
    # when the note already exists and is just being rewritten.
    # This whole dict is AnkiConnect's own request contract either way, not something
    # invented by this project- every AnkiConnect call is a POST with this "action"/
    # "version"/"params" envelope. "modelName" is AnkiConnect's own term for what this
    # project (and Anki's UI) calls a "note type"- NOTE_TYPE is passed in under that key
    # because that's the name the API itself expects, not a naming inconsistency here.
    # allowDuplicate: False (addNote only) means AnkiConnect will reject rather than
    # silently accept a note that already exists in the deck- see the raise below for
    # how that surfaces.

    data = _post_to_ankiconnect(action, params)
    # _post_to_ankiconnect raises AnkiConnectError itself for both a transport failure
    # (AnkiConnect unreachable) and a logical failure reported inside a normal 200
    # response (e.g. AnkiConnect rejecting the note as a duplicate)- see its definition
    # above, and test_export_card_raises_on_anki_error / test_export_card_raises_when_
    # anki_unreachable in tests/test_anki.py for the two cases.

    return data["result"] if anki_note_id is None else anki_note_id
    # addNote's own "result" is the new note's ID, assigned by Anki- that's the value the
    # caller needs to persist (see record_export() in backend/db.py) so a *later*
    # re-export can target this exact note. updateNoteFields' "result" is just null on
    # success (it doesn't hand back an ID, since the caller already supplied one)- so in
    # that branch, the note ID to persist is simply the same anki_note_id passed in,
    # unchanged.
