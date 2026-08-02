import os

import requests

from backend.models import ExportRequest

ANKICONNECT_URL = os.getenv("ANKICONNECT_URL", "http://localhost:8765")
DECK_NAME = os.getenv("ANKI_DECK_NAME", "Japanese")
NOTE_TYPE = os.getenv("ANKI_NOTE_TYPE", "Basic")


class AnkiConnectError(Exception):
    """Raised when AnkiConnect is unreachable or returns an error."""


def _build_fields(card: ExportRequest) -> dict:
    # "Basic" only has Front/Back- fold the six card fields into those two
    # until a custom Japanese note type exists in Anki (see README Configuration).
    # "Folding" in this context means to combine, flatten or merge multiple pieces of data into fewer containers.
    front = f"{card.expression}<br>{card.reading}"
    back = (
        f"<b>Definition:</b> {card.definition}<br>"
        f"<b>Nuance:</b> {card.nuance}<br>"
        f"<b>Example:</b> {card.example}<br>"
        f"<b>JLPT:</b> {card.jlpt}"
    )
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

    try:
        response = requests.post(ANKICONNECT_URL, json=payload, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AnkiConnectError(
            f"Could not reach AnkiConnect at {ANKICONNECT_URL}: {exc}"
        ) from exc

    data = response.json()
    if data.get("error"):
        raise AnkiConnectError(data["error"])
