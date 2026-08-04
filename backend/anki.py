import os
# os.getenv reads environment variables- used below so AnkiConnect's URL, deck name,
# and note type can all be overridden without touching this file (see README Configuration).

import requests
# The same `requests` library backend/llm.py uses for OpenRouter- here it's the HTTP
# client used to talk to AnkiConnect instead.

from backend.models import ExportRequest

ANKICONNECT_URL = os.getenv("ANKICONNECT_URL", "http://localhost:8765")
DECK_NAME = os.getenv("ANKI_DECK_NAME", "Japanese")
NOTE_TYPE = os.getenv("ANKI_NOTE_TYPE", "Basic")
# os.getenv("NAME", default) returns the environment variable's value if it's set, or
# the given default otherwise- so these three constants work out of the box for a
# fresh install (default Anki deck/note type, default AnkiConnect port) while still
# being overridable per-user without any code change.


class AnkiConnectError(Exception):
    """Raised when AnkiConnect is unreachable or returns an error."""
    # backend/main.py's /export route catches this specifically and turns it into an
    # HTTP 503 response- see the two distinct raise sites in export_card() below for
    # the two different situations this same exception type covers.


def _build_fields(card: ExportRequest) -> dict:
    # "Basic" only has Front/Back- fold the six card fields into those two
    # until a custom Japanese note type exists in Anki (see README Configuration).
    # "Folding" in this context means to combine, flatten or merge multiple pieces of data into fewer containers.
    front = f"{card.expression}"
    back = (
        f"<b>Reading:</b> {card.reading}<br>"
        f"<b>Definition:</b> {card.definition}<br>"
        f"<b>Nuance:</b> {card.nuance}<br>"
        f"<b>Example:</b> {card.example}<br>"
        f"<b>JLPT:</b> {card.jlpt}"
    )
    # Anki renders card fields as HTML, not plain text- <b> and <br> here are actual
    # HTML tags, not a formatting convention specific to this project. That's also why
    # this function returns a plain dict rather than an ExportRequest: AnkiConnect's
    # own API expects note fields as a {"FieldName": "HTML string"} mapping, keyed by
    # the exact field names the target note type defines ("Front"/"Back" for "Basic").
    return {"Front": front, "Back": back}


def export_card(card: ExportRequest) -> None:
    payload = {
        "action": "addNote",
        "version": 6,
        "params": {
            "note": {
                "deckName": DECK_NAME,
                "modelName": NOTE_TYPE,
                "fields": _build_fields(card),
                "options": {"allowDuplicate": False},
                "tags": ["anki-tool-v2"],
            }
        },
    }
    # This whole dict is AnkiConnect's own request contract, not something invented by
    # this project- every AnkiConnect call is a POST with this "action"/"version"/
    # "params" envelope, regardless of which action is being invoked (addNote here).
    # "modelName" is AnkiConnect's own term for what this project (and Anki's UI) calls
    # a "note type"- NOTE_TYPE is passed in under that key because that's the name the
    # API itself expects, not a naming inconsistency in this codebase.
    # allowDuplicate: False means AnkiConnect will reject (rather than silently accept)
    # a note that already exists in the deck- see the raise below for how that surfaces.

    try:
        response = requests.post(ANKICONNECT_URL, json=payload, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AnkiConnectError(
            f"Could not reach AnkiConnect at {ANKICONNECT_URL}: {exc}"
        ) from exc
    # This except block only covers *transport*-level failures- AnkiConnect not running,
    # connection refused, timeout, or an HTTP error status. `raise ... from exc` re-raises
    # as an AnkiConnectError but keeps the original exception attached as its __cause__,
    # so a full traceback still shows both the AnkiConnectError and the underlying
    # requests exception that triggered it, instead of losing that context.

    data = response.json()
    if data.get("error"):
        raise AnkiConnectError(data["error"])
    # This second check is separate from the try/except above because AnkiConnect can
    # respond with a normal HTTP 200 (so raise_for_status() above doesn't complain) while
    # still reporting a logical failure inside its own JSON body- e.g. rejecting the note
    # as a duplicate. data.get("error") returns None (falsy) when nothing went wrong, or
    # AnkiConnect's error message string when something did- exactly the case
    # test_export_card_raises_on_anki_error in tests/test_anki.py exercises.
