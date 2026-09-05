import json
from pathlib import Path
from typing import Literal


MAX_ITEMS = 12

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

Section = Literal["vocab", "grammar", "reading"]

# REQUIRED_ITEM_KEY is a dictionary object
REQUIRED_ITEM_KEY: dict[Section, str] = {
    "vocab": "word",
    "grammar": "pattern",
    "reading": "topic",
}


class DatasetNotFoundError(Exception):
    """Raised when data/<level>/<section>.json doesn't exist."""


class DatasetValidationError(Exception):
    """Raised when a dataset file exists but its contents don't match the expected shape."""


def load_section(level: str, section: Section) -> list[dict]:
    path = DATA_DIR / level.lower() / f"{section}.json"
    if not path.exists():
        raise DatasetNotFoundError(f"No dataset file found at {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DatasetValidationError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise DatasetValidationError(f"{path}: top level must be a JSON object")

    if raw.get("section") != section:
        raise DatasetValidationError(
            f"{path}: wrapper 'section' is {raw.get('section')!r}, expected {section!r}"
        )
    if raw.get("level") != level.upper():
        raise DatasetValidationError(
            f"{path}: wrapper 'level' is {raw.get('level')!r}, expected {level.upper()!r}"
        )

    items = raw.get("items")
    if not isinstance(items, list) or not items:
        raise DatasetValidationError(f"{path}: 'items' must be a non-empty list")
    if len(items) > MAX_ITEMS:
        raise DatasetValidationError(
            f"{path}: contains {len(items)} items- the limit is {MAX_ITEMS} per file."
        )

    required_key = REQUIRED_ITEM_KEY[section]
    for item in items:
        if not isinstance(item, dict) or not item.get(required_key):
            raise DatasetValidationError(
                f"{path}: every item must be an object with a non-empty '{required_key}' key"
            )

    return items
