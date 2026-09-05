# test_datasets.py mirrors test_batch.py's role, but for backend/datasets.py's
# load_section()- the dataset-driven equivalent of batch.py's parse_and_validate(),
# reading a local data/<level>/<section>.json file off disk instead of parsing an
# uploaded .txt string.
import json

import pytest

from backend.datasets import (
    DatasetNotFoundError,
    DatasetValidationError,
    MAX_ITEMS,
    load_section,
)


def _write_dataset(path, section, level, items):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"section": section, "level": level, "items": items}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_loads_valid_vocab_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.datasets.DATA_DIR", tmp_path)
    _write_dataset(tmp_path / "n2" / "vocab.json", "vocab", "N2", [{"word": "検討"}])

    assert load_section("N2", "vocab") == [{"word": "検討"}]
    # level is passed in already-resolved (see backend/main.py's _resolve_level)- the
    # file path is built from level.lower(), so "N2" maps to data/n2/vocab.json.


def test_loads_valid_grammar_dataset_with_optional_hints(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.datasets.DATA_DIR", tmp_path)
    item = {"pattern": "〜ざるを得ない", "connection_hint": "動詞ない形+ざるを得ない", "meaning_hint": None}
    _write_dataset(tmp_path / "n2" / "grammar.json", "grammar", "N2", [item])

    assert load_section("N2", "grammar") == [item]


def test_missing_file_raises_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.datasets.DATA_DIR", tmp_path)
    with pytest.raises(DatasetNotFoundError):
        load_section("N2", "reading")


def test_malformed_json_raises_validation_error(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.datasets.DATA_DIR", tmp_path)
    path = tmp_path / "n2" / "vocab.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(DatasetValidationError, match="not valid JSON"):
        load_section("N2", "vocab")


def test_mismatched_wrapper_section_raises_validation_error(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.datasets.DATA_DIR", tmp_path)
    _write_dataset(tmp_path / "n2" / "vocab.json", "grammar", "N2", [{"word": "検討"}])
    # File on disk claims to be "grammar" even though it's requested (and located) as
    # "vocab"- catches a misnamed/misplaced file rather than silently generating from it.

    with pytest.raises(DatasetValidationError, match="section"):
        load_section("N2", "vocab")


def test_mismatched_wrapper_level_raises_validation_error(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.datasets.DATA_DIR", tmp_path)
    _write_dataset(tmp_path / "n2" / "vocab.json", "vocab", "N3", [{"word": "検討"}])

    with pytest.raises(DatasetValidationError, match="level"):
        load_section("N2", "vocab")


def test_empty_items_raises_validation_error(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.datasets.DATA_DIR", tmp_path)
    _write_dataset(tmp_path / "n2" / "vocab.json", "vocab", "N2", [])

    with pytest.raises(DatasetValidationError, match="non-empty"):
        load_section("N2", "vocab")


def test_too_many_items_raises_validation_error(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.datasets.DATA_DIR", tmp_path)
    items = [{"word": "猫"} for _ in range(MAX_ITEMS + 1)]
    _write_dataset(tmp_path / "n2" / "vocab.json", "vocab", "N2", items)

    with pytest.raises(DatasetValidationError, match=str(MAX_ITEMS)):
        load_section("N2", "vocab")


def test_accepts_exactly_max_items(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.datasets.DATA_DIR", tmp_path)
    items = [{"word": "猫"} for _ in range(MAX_ITEMS)]
    _write_dataset(tmp_path / "n2" / "vocab.json", "vocab", "N2", items)

    assert len(load_section("N2", "vocab")) == MAX_ITEMS


def test_item_missing_required_key_raises_validation_error(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.datasets.DATA_DIR", tmp_path)
    _write_dataset(tmp_path / "n2" / "grammar.json", "grammar", "N2", [{"connection_hint": "x"}])
    # Missing "pattern"- grammar's own required key (see backend/datasets.py's
    # REQUIRED_ITEM_KEY).

    with pytest.raises(DatasetValidationError, match="pattern"):
        load_section("N2", "grammar")


def test_item_with_empty_required_key_raises_validation_error(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.datasets.DATA_DIR", tmp_path)
    _write_dataset(tmp_path / "n2" / "reading.json", "reading", "N2", [{"topic": ""}])

    with pytest.raises(DatasetValidationError, match="topic"):
        load_section("N2", "reading")
