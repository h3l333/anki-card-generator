import json
from types import SimpleNamespace
from unittest.mock import ANY, patch

from backend.anki import AnkiConnectError
from backend.batch import BatchValidationError
from backend.llm import LLMError
from backend.models import BatchCardResult, CardDraft

# test_main.py doesn't re-test the LLM or Anki logic itself (that's already covered by
# test_llm.py and test_anki.py)- instead it checks that each route in backend/main.py wires
# things together correctly: calling the right backend function, and mapping each custom
# exception type to the right HTTP status code (LLMError -> 502, BatchValidationError -> 400,
# AnkiConnectError -> 503). Every test below patches the relevant function as imported into
# backend/main.py's own namespace (e.g. "backend.main.generate_card", not
# "backend.llm.generate_card")- main.py does `from backend.llm import generate_card`, which
# creates a separate reference inside backend.main's namespace, and that's the reference the
# route handler's unqualified `generate_card(...)` call actually looks up.


def _read_batch_stream(response):
    # POST /generate/batch streams newline-delimited JSON rather than one JSON document
    # (see backend/main.py::_stream_batch_results), so response.json() doesn't work here-
    # TestClient still buffers the whole streamed body into response.text before this
    # function runs, it just isn't valid as a single json.loads() call. The first line is
    # always {"total": N}; every line after that carries one word's BatchCardResult.
    lines = [json.loads(line) for line in response.text.strip().split("\n")]
    total = lines[0]["total"]
    results = [line["result"] for line in lines[1:]]
    return total, results


def test_generate_route_returns_card(client, sample_card_json):
    card = CardDraft(**sample_card_json)
    with (
        patch("backend.main.find_word_by_kanji", return_value=None),
        patch("backend.main.generate_card", return_value=card),
        patch("backend.main.insert_word", return_value=1),
        patch("backend.main.insert_card") as mock_insert_card,
    ):
        response = client.post("/generate", json={"word": "大人"})
    assert response.status_code == 200
    body = response.json()
    assert body["word_id"] == 1
    assert body["duplicate"] is False
    assert body["card"]["expression"] == "大人"
    mock_insert_card.assert_called_once()
    # `client` comes from the `client` fixture in conftest.py- a TestClient wrapping the real
    # FastAPI() app object from backend/main.py. Posting to "/generate" runs backend/main.py's
    # actual generate() route function in-process. find_word_by_kanji is mocked to return None
    # (no existing record) so the route takes the fresh-generation branch; insert_word/
    # insert_card are mocked too so this test never touches a real database- it's only
    # checking that the route calls the right functions and shapes the response correctly,
    # the same scope test_db.py-style DB tests would leave to their own file instead.


def test_generate_route_returns_existing_card_without_calling_llm(
    client, sample_card_json
):
    existing_word = SimpleNamespace(id=7, kanji="大人", reading=sample_card_json["reading"])
    existing_card = SimpleNamespace(
        definition_ja=sample_card_json["definition_ja"],
        nuance=sample_card_json["nuance"],
        synonyms=sample_card_json["synonyms"],
        antonyms=sample_card_json["antonyms"],
        example_sentence=sample_card_json["example_sentence"],
        jlpt_level=sample_card_json["jlpt_level"],
    )
    with (
        patch("backend.main.find_word_by_kanji", return_value=existing_word),
        patch("backend.main.get_card", return_value=existing_card),
        patch("backend.main.generate_card") as mock_generate_card,
    ):
        response = client.post("/generate", json={"word": "大人"})
    assert response.status_code == 200
    body = response.json()
    assert body["word_id"] == 7
    assert body["duplicate"] is True
    assert body["card"]["expression"] == "大人"
    mock_generate_card.assert_not_called()
    # The duplicate-check branch: find_word_by_kanji returning something means the word's
    # already in Postgres, so the route must build its response from that (via get_card)
    # without ever calling generate_card- this is the token-saving short-circuit the whole
    # DB-lookup-before-generation change exists for, so it's worth asserting on directly
    # rather than just checking the response body. SimpleNamespace stands in for the real
    # SQLAlchemy Word/Card rows here since the route only reads plain attributes off them.


def test_generate_route_maps_llm_error_to_502(client):
    with (
        patch("backend.main.find_word_by_kanji", return_value=None),
        patch("backend.main.generate_card", side_effect=LLMError("boom")),
    ):
        response = client.post("/generate", json={"word": "大人"})
    assert response.status_code == 502
    assert response.json()["detail"] == "boom"
    # backend/main.py's generate() route catches LLMError specifically and re-raises it as
    # HTTPException(status_code=502, detail=str(exc))- this checks that mapping directly.
    # find_word_by_kanji is mocked to return None so the route actually reaches generate_card
    # in the first place, same reasoning as test_generate_route_returns_card above.


def test_generate_batch_route_returns_results(client, sample_card_json):
    card = CardDraft(**sample_card_json)
    results = [BatchCardResult(word="大人", card=card)]
    with (
        patch("backend.main.parse_and_validate", return_value=["大人"]),
        patch("backend.main.find_word_by_kanji", return_value=None),
        patch("backend.main.generate_cards_batch", return_value=results),
        patch("backend.main.insert_word", return_value=9) as mock_insert_word,
        patch("backend.main.insert_card") as mock_insert_card,
    ):
        response = client.post("/generate/batch", json={"file_content": "大人"})
    assert response.status_code == 200
    total, results = _read_batch_stream(response)
    assert total == 1
    body = results[0]
    assert body["word"] == "大人"
    assert body["word_id"] == 9
    mock_insert_word.assert_called_once_with(kanji="大人", reading=card.reading, source="batch")
    mock_insert_card.assert_called_once()
    # /generate/batch calls parse_and_validate then generate_cards_batch, same as before-
    # both still need mocking here since this test is only about the route's wiring, not
    # either function's own internal logic. New since batch/Postgres persistence was added:
    # insert_word/insert_card are also mocked (same as test_generate_route_returns_card
    # does for /generate), and the response's word_id is asserted directly- that's the
    # field the frontend now needs from a batch result to track/update a later export
    # (see backend/models.py's BatchCardResult and frontend/index.js's buildCarouselCard).
    # find_word_by_kanji is mocked to return None (no existing record) since the route now
    # calls it per word before deciding what to generate- same reasoning as /generate's own
    # tests- otherwise this test would hit a real, unmocked Postgres lookup.


def test_generate_batch_route_skips_llm_for_duplicate_word(client, sample_card_json):
    card = CardDraft(**sample_card_json)
    existing_word = SimpleNamespace(id=7, kanji="大人", reading=sample_card_json["reading"])
    existing_card = SimpleNamespace(
        definition_ja=sample_card_json["definition_ja"],
        nuance=sample_card_json["nuance"],
        synonyms=sample_card_json["synonyms"],
        antonyms=sample_card_json["antonyms"],
        example_sentence=sample_card_json["example_sentence"],
        jlpt_level=sample_card_json["jlpt_level"],
    )
    new_word_result = BatchCardResult(word="新語", card=card)

    def fake_find_word_by_kanji(word):
        return existing_word if word == "大人" else None

    with (
        patch("backend.main.parse_and_validate", return_value=["大人", "新語"]),
        patch("backend.main.find_word_by_kanji", side_effect=fake_find_word_by_kanji),
        patch("backend.main.get_card", return_value=existing_card),
        patch(
            "backend.main.generate_cards_batch", return_value=[new_word_result]
        ) as mock_generate_cards_batch,
        patch("backend.main.insert_word", return_value=9) as mock_insert_word,
        patch("backend.main.insert_card") as mock_insert_card,
    ):
        response = client.post("/generate/batch", json={"file_content": "大人\n新語"})
    assert response.status_code == 200
    total, results = _read_batch_stream(response)
    assert total == 2
    assert [r["word"] for r in results] == ["大人", "新語"]

    duplicate_result, generated_result = results
    assert duplicate_result["duplicate"] is True
    assert duplicate_result["word_id"] == 7
    assert duplicate_result["card"]["expression"] == "大人"
    assert generated_result["duplicate"] is False
    assert generated_result["word_id"] == 9

    mock_generate_cards_batch.assert_called_once_with(["新語"])
    mock_insert_word.assert_called_once_with(kanji="新語", reading=card.reading, source="batch")
    mock_insert_card.assert_called_once()
    # Mirrors test_generate_route_returns_existing_card_without_calling_llm above, but for a
    # mixed batch: "大人" is already in Postgres (find_word_by_kanji hits), "新語" isn't. The
    # duplicate result must come back with duplicate=True, its existing word_id, and a card
    # rebuilt from Postgres- and generate_cards_batch must only ever be called with the
    # words that actually need generating (asserted via call args, not just call count), so a
    # duplicate word never reaches an LLM call. insert_word/insert_card must fire once, only
    # for the genuinely new word- re-inserting the duplicate would create a second row for
    # the same kanji. Streamed line order ("大人" then "新語") must match the uploaded
    # file's order even though the duplicate was resolved (near-instantly, via Postgres)
    # before the LLM call for "新語" even started- see _stream_batch_results in
    # backend/main.py for how it re-walks `words` in file order to guarantee this.


# Directly checks the progress-counter data itself (rather than just the final `result`
# each line carries, like the tests above)- a 3-word batch mixing a duplicate, a
# successful generation, and a failed one should still produce a leading {"total": 3}
# line followed by "completed" counting 1, 2, 3 in file order, regardless of which kind
# of result each word actually produced.
def test_generate_batch_route_streams_progress_counts(client, sample_card_json):
    card = CardDraft(**sample_card_json)
    existing_word = SimpleNamespace(id=7, kanji="大人", reading=sample_card_json["reading"])
    existing_card = SimpleNamespace(
        definition_ja=sample_card_json["definition_ja"],
        nuance=sample_card_json["nuance"],
        synonyms=sample_card_json["synonyms"],
        antonyms=sample_card_json["antonyms"],
        example_sentence=sample_card_json["example_sentence"],
        jlpt_level=sample_card_json["jlpt_level"],
    )
    generated_results = [
        BatchCardResult(word="新語", card=card),
        BatchCardResult(word="失敗語", error="boom"),
    ]

    def fake_find_word_by_kanji(word):
        return existing_word if word == "大人" else None

    with (
        patch(
            "backend.main.parse_and_validate", return_value=["大人", "新語", "失敗語"]
        ),
        patch("backend.main.find_word_by_kanji", side_effect=fake_find_word_by_kanji),
        patch("backend.main.get_card", return_value=existing_card),
        patch("backend.main.generate_cards_batch", return_value=generated_results),
        patch("backend.main.insert_word", return_value=9),
        patch("backend.main.insert_card"),
    ):
        response = client.post(
            "/generate/batch", json={"file_content": "大人\n新語\n失敗語"}
        )

    lines = [json.loads(line) for line in response.text.strip().split("\n")]
    assert lines[0] == {"total": 3}
    assert [line["completed"] for line in lines[1:]] == [1, 2, 3]
    assert [line["total"] for line in lines[1:]] == [3, 3, 3]
    assert [line["result"]["word"] for line in lines[1:]] == ["大人", "新語", "失敗語"]
    # "total" is repeated on every per-word line (not just the leading one)- lets the
    # frontend update its "X/N" counter from any single line without having to remember
    # N separately from the first line it read.


def test_generate_batch_route_skips_persistence_for_failed_words(client):
    results = [BatchCardResult(word="大人", error="boom")]
    with (
        patch("backend.main.parse_and_validate", return_value=["大人"]),
        patch("backend.main.find_word_by_kanji", return_value=None),
        patch("backend.main.generate_cards_batch", return_value=results),
        patch("backend.main.insert_word") as mock_insert_word,
        patch("backend.main.insert_card") as mock_insert_card,
    ):
        response = client.post("/generate/batch", json={"file_content": "大人"})
    assert response.status_code == 200
    _total, results = _read_batch_stream(response)
    assert results[0]["word_id"] is None
    mock_insert_word.assert_not_called()
    mock_insert_card.assert_not_called()
    # A result with no card (generate_card failed for this word- see BatchCardResult) has
    # nothing to persist, so the route's persistence loop must skip it entirely rather than
    # calling insert_word/insert_card with a None card's attributes. find_word_by_kanji is
    # mocked to return None so the route's per-word duplicate check reaches
    # generate_cards_batch for this word instead of hitting a real Postgres lookup.


def test_generate_batch_route_maps_validation_error_to_400(client):
    with patch(
        "backend.main.parse_and_validate", side_effect=BatchValidationError("bad file")
    ):
        response = client.post("/generate/batch", json={"file_content": "???"})
    assert response.status_code == 400
    assert response.json()["detail"] == "bad file"
    # backend/main.py's generate_batch() route catches BatchValidationError specifically and
    # re-raises it as HTTPException(status_code=400, detail=str(exc)), before ever reaching
    # generate_cards_batch- that's why only parse_and_validate needs mocking in this test.


def test_export_route_succeeds(client, sample_export_request):
    with (
        patch("backend.main.export_card", return_value=None) as mock_export_card,
        patch("backend.main.get_latest_export") as mock_get_latest_export,
        patch("backend.main.record_export") as mock_record_export,
    ):
        response = client.post("/export", json=sample_export_request.model_dump())
    assert response.status_code == 200
    assert response.json() == {"status": "exported"}
    mock_get_latest_export.assert_not_called()
    mock_record_export.assert_not_called()
    mock_export_card.assert_called_once_with(ANY, anki_note_id=None)
    # sample_export_request (from conftest.py) leaves word_id at its default of None (see
    # ExportRequest in backend/models.py)- the same shape a batch-flow export currently
    # sends, since batch cards have no word_id yet (see backend/models.py's comment on
    # why). With no word_id, the route must skip both DB calls entirely rather than error-
    # that's the current, intentional fallback behavior for batch exports, not a gap in
    # this test. client.post(json=...) needs a plain dict, hence .model_dump().


def test_export_route_maps_anki_error_to_503(client, sample_export_request):
    with (
        patch("backend.main.export_card", side_effect=AnkiConnectError("unreachable")),
        patch("backend.main.record_export") as mock_record_export,
    ):
        response = client.post("/export", json=sample_export_request.model_dump())
    assert response.status_code == 503
    assert response.json()["detail"] == "unreachable"
    mock_record_export.assert_not_called()
    # backend/main.py's export() route catches AnkiConnectError specifically and re-raises it
    # as HTTPException(status_code=503, detail=str(exc))- this checks that final mapping.
    # record_export() must never run here- a failed AnkiConnect call means nothing was
    # actually exported, so nothing should be recorded either (see the ordering note in
    # backend/main.py's export() route).


def test_export_route_records_new_note_when_no_prior_export(client, sample_export_request):
    payload = {**sample_export_request.model_dump(), "word_id": 5}
    with (
        patch("backend.main.get_latest_export", return_value=None),
        patch("backend.main.export_card", return_value=555) as mock_export_card,
        patch("backend.main.record_export") as mock_record_export,
    ):
        response = client.post("/export", json=payload)
    assert response.status_code == 200
    mock_export_card.assert_called_once_with(ANY, anki_note_id=None)
    mock_record_export.assert_called_once_with(5, 555)
    # word_id=5 with get_latest_export returning None means this word has never been
    # exported before- export_card() is called with anki_note_id=None (addNote, per
    # backend/anki.py), and whatever note ID it returns (555, mocked here as if
    # AnkiConnect assigned it) gets recorded against word_id 5.


def test_export_route_updates_existing_note_when_prior_export_exists(
    client, sample_export_request
):
    payload = {**sample_export_request.model_dump(), "word_id": 5}
    with (
        patch(
            "backend.main.get_latest_export",
            return_value=SimpleNamespace(anki_note_id=777),
        ),
        patch("backend.main.export_card", return_value=777) as mock_export_card,
        patch("backend.main.record_export") as mock_record_export,
    ):
        response = client.post("/export", json=payload)
    assert response.status_code == 200
    mock_export_card.assert_called_once_with(ANY, anki_note_id=777)
    mock_record_export.assert_called_once_with(5, 777)
    # get_latest_export returning a prior export (note ID 777) means export_card() must be
    # called with that anki_note_id- switching it to updateNoteFields (backend/anki.py)
    # instead of addNote, so the existing Anki note gets rewritten rather than duplicated.
    # A new exports row still gets recorded afterwards (record_export), per the "one row
    # per export event" design in DATABASE.md- re-exporting isn't exempt from history.
