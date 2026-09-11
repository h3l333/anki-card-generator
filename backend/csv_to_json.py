import json
import csv
from pathlib import Path
from datasets import MAX_ITEMS, REQUIRED_ITEM_KEY

_CSV_FILES_PATH = Path(__name__).resolve().parent / "csv_data"

def csv_to_dicts(csv_path: Path) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return [
            {k.lower().replace(" ", "_"): v for k, v in row.items()}
            for row in csv.DictReader(f)
        ]

def dicts_to_json(rows: list[dict]) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=2)


def filter_by_field(rows: list[dict], key: str, value: str) -> list[dict]:
    return [row for row in rows if row.get(key) == value]


def build_dataset(rows: list[dict], level: str, section: str) -> dict:
    items = filter_by_field(rows, "jlpt_level", level.upper())
    required_key = REQUIRED_ITEM_KEY[section]
    items = [
        {(required_key if k == "original" else k): v for k, v in item.items()}
        for item in items
    ]
    # Rename the CSV's "original" key to whatever key this section requires (e.g. "word" for vocab).
    # Do this for every filtered item.
    return {
        "section": section,
        "level": level.upper(),
        "items": items,
    }


rows = csv_to_dicts(_CSV_FILES_PATH / "jlpt_vocab.csv")
dataset = build_dataset(rows, "n2", "vocab")
print(json.dumps(dataset, ensure_ascii=False, indent=2))
