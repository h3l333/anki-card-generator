import json
from pathlib import Path
from typing import Literal

MAX_ITEMS = 999

# Resolves path corresponding to the JLPT data that the program draws from to build
# vocab, grammar, and reading cards.
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# In Python, literals are fixed values written directly in Python code.
# The following line is a type hint that restricts Section to the written three string values.
# Reminder: A literal is any value represented directly rather than through a variable or func. call.
# Example: foo = Literal[3] indicates that foo must be exactly equal to 3.
# After the following line, Section = typing.Literal['vocab', 'grammar', 'reading']
Section = Literal["vocab", "grammar", "reading"]

# REQUIRED_ITEM_KEY is a dictionary object.
# Section is the key, str is the value. This dictionary maps out sections to their required item keys.
REQUIRED_ITEM_KEY: dict[Section, str] = {
    "vocab": "word",
    "grammar": "pattern",
    "reading": "topic",
}


class DatasetNotFoundError(Exception):
    """Raised when data/<level>/<section>.json doesn't exist."""


class DatasetValidationError(Exception):
    """Raised when a dataset file exists but its contents don't match the expected shape."""

# The "level" parameter just points to an actual JLPT level. lower() just takes a string
# to lower case.
def load_section(level: str, section: Section) -> list[dict]:
    path = DATA_DIR / level.lower() / f"{section}.json"
    if not path.exists():
        raise DatasetNotFoundError(f"No dataset file found at {path}")

    try:
        # read_text() opens a file in text mode, reads it and closes it.
        # Note: text mode is used for reading plain text files, source code, HTML, CSV...
        #   Binary mode is used for non-text files; images, audio, executable programs.
        # loads() is a function native to the json Python API that takes a string
        # containing a JSON object and transforms it into a Python object.
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DatasetValidationError(f"{path} is not valid JSON: {exc}") from exc

    # The isinstance function, native to Python, returns if an object is an instance
    # of a given class or not.
    if not isinstance(raw, dict):
        raise DatasetValidationError(f"{path}: top level must be a JSON object")

    # get() is also part of the Python json API. It retrieves the value of a passed in key.
    # The following two checks raise errors in the case that there is a mismatch between the JSON
    # file's section and level in the directory/file name and in the actual file itself- they act
    # as safeguards in the face of incorrect labeling.
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

    # REQUIRED_ITEM_KEY[] maps each section to its required "item".
    # See data files to see corresponding items and garner a better understanding.
    required_key = REQUIRED_ITEM_KEY[section]
    for item in items:
        if not isinstance(item, dict) or not item.get(required_key):
            raise DatasetValidationError(
                f"{path}: every item must be an object with a non-empty '{required_key}' key"
            )

    return items
