# test_db.py exercises backend/db.py directly against a real Postgres database, unlike
# test_anki.py/test_llm.py/test_main.py which all patch out their respective network/db
# boundary. There's no separate test database configured (see CLAUDE.md)- these tests run
# against the same DATABASE_URL backend/main.py itself connects to (docker-compose.yml's
# defaults), so `docker compose up -d` must be running first. If Postgres isn't reachable,
# tests here fail with a connection error rather than being skipped- that's read as "is the
# container up", not "is the code broken".
import pytest
from datetime import datetime

from sqlalchemy import delete

from backend.db import (
    Card,
    Export,
    SessionLocal,
    Word,
    find_word_by_kanji,
    get_card,
    get_latest_export,
    init_db,
    insert_card,
    insert_word,
    record_export,
)

# Fullwidth-underscore marker keeps every row this file writes visually obvious as test
# junk in a `SELECT * FROM words` (like the one used to verify the level column above)
# even in the unlikely case the cleanup fixture below doesn't run.
TEST_KANJI = "＿テスト単語＿"


@pytest.fixture(autouse=True, scope="module")
def _init_db():
    init_db()
# create_all() only creates tables that don't already exist yet (see backend/db.py), so
# this is safe to call even though the app's own lifespan hook has already created them
# against a dev database- it's a no-op there, and what actually stands up the schema if
# these tests are ever pointed at a fresh, empty database.


@pytest.fixture
def cleanup_words():
    created_ids: list[int] = []
    yield created_ids
    with SessionLocal() as session:
        for word_id in created_ids:
            session.execute(delete(Export).where(Export.word_id == word_id))
            session.execute(delete(Card).where(Card.word_id == word_id))
            session.execute(delete(Word).where(Word.id == word_id))
            session.commit()
# Tests append the id insert_word() hands back to this list as soon as they get it, so
# teardown still cleans up even if a later assertion in the same test fails- yield-based
# pytest fixtures run their teardown in a finally, not only on a clean return. Exports and
# Cards are deleted before their parent Word to respect the foreign keys.


def test_insert_word_returns_id_and_persists_fields(cleanup_words):
    word_id = insert_word(TEST_KANJI, "てすと", "manual", "N3")
    cleanup_words.append(word_id)

    assert isinstance(word_id, int)
    found = find_word_by_kanji(TEST_KANJI, "N3")
    assert found.id == word_id
    assert found.kanji == TEST_KANJI
    assert found.reading == "てすと"
    assert found.source == "manual"
    assert found.level == "N3"
    assert found.created_at is not None


def test_find_word_by_kanji_returns_none_when_not_found():
    assert find_word_by_kanji("＿存在しない単語＿", "N3") is None


def test_find_word_by_kanji_treats_different_levels_as_distinct_words(cleanup_words):
    id_n3 = insert_word(TEST_KANJI, "てすと", "manual", "N3")
    id_n1 = insert_word(TEST_KANJI, "てすと", "manual", "N1")
    cleanup_words += [id_n3, id_n1]

    found_n3 = find_word_by_kanji(TEST_KANJI, "N3")
    found_n1 = find_word_by_kanji(TEST_KANJI, "N1")

    assert found_n3.id == id_n3
    assert found_n1.id == id_n1
    assert found_n3.id != found_n1.id
# Same kanji, two levels- this is the duplicate-check key backend/db.py's Word docstring
# describes (kanji, level) together, not kanji alone- a word already generated at one
# level must not shadow a lookup for the same word at a different level.


def test_get_card_returns_none_when_word_has_no_card(cleanup_words):
    word_id = insert_word(TEST_KANJI, "てすと", "manual", "N3")
    cleanup_words.append(word_id)

    assert get_card(word_id) is None


def test_insert_card_persists_all_fields(cleanup_words):
    word_id = insert_word(TEST_KANJI, "てすと", "manual", "N3")
    cleanup_words.append(word_id)

    insert_card(
        word_id,
        definition_ja="定義",
        nuance="ニュアンス",
        synonyms="類義語",
        antonyms="対義語",
        example_sentence="例文です。",
        jlpt_level="N4",
    )

    card = get_card(word_id)
    assert card.definition_ja == "定義"
    assert card.nuance == "ニュアンス"
    assert card.synonyms == "類義語"
    assert card.antonyms == "対義語"
    assert card.example_sentence == "例文です。"
    assert card.jlpt_level == "N4"
    assert card.exported is False
# jlpt_level ("N4") is deliberately different from the Word's own level ("N3") here- they're
# independent fields (the word's target-learner level vs. the model's own difficulty estimate
# for the word, per CLAUDE.md), and this test would miss a field mix-up if both were "N3".


def test_get_latest_export_returns_none_when_never_exported(cleanup_words):
    word_id = insert_word(TEST_KANJI, "てすと", "manual", "N3")
    cleanup_words.append(word_id)
    insert_card(word_id, "def", "nuance", "syn", "ant", "example", "N3")

    assert get_latest_export(word_id) is None


def test_record_export_creates_export_and_marks_card_exported(cleanup_words):
    word_id = insert_word(TEST_KANJI, "てすと", "manual", "N3")
    cleanup_words.append(word_id)
    insert_card(word_id, "def", "nuance", "syn", "ant", "example", "N3")

    record_export(word_id, anki_note_id=555)

    card = get_card(word_id)
    assert card.exported is True
    latest = get_latest_export(word_id)
    assert latest is not None
    assert latest.anki_note_id == 555


def test_get_latest_export_returns_most_recent_by_time(cleanup_words):
    word_id = insert_word(TEST_KANJI, "てすと", "manual", "N3")
    cleanup_words.append(word_id)
    insert_card(word_id, "def", "nuance", "syn", "ant", "example", "N3")

    # Setting exported_at explicitly (rather than calling record_export twice back to back
    # and relying on wall-clock ordering) keeps this deterministic- two commits issued
    # microseconds apart could otherwise land on the same NOW() value under load.
    with SessionLocal() as session:
        session.add(
            Export(word_id=word_id, anki_note_id=111, exported_at=datetime(2020, 1, 1))
        )
        session.add(
            Export(word_id=word_id, anki_note_id=222, exported_at=datetime(2024, 1, 1))
        )
        session.commit()

    latest = get_latest_export(word_id)
    assert latest.anki_note_id == 222
