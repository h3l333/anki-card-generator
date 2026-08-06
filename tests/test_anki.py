# `test_anki.py` verifies that the bridge between the app and Anki works as expected, *without*
# needing Anki to be open/running.
from unittest.mock import MagicMock, patch
# Import key utilities from Python's built-in standard library.
#   - MagicMock: Mock object used to substitute real classes or objects during testing.
#   - patch: Context manager that, when used with the `with` statement temporarily replaces an object
#       with a mock for only the code inside the `with` block.
#
# Note: `patch` can also be used as a
#   decorator that temporarily replaces hardcoded functions/classes with mock objects during a single test run.
#   In Python, a decorator is a function that wraps around another to change or extend its behaviour without modifying
#   the code inside it.

import pytest
import requests

from backend.anki import AnkiConnectError, _build_fields, export_card

# backend/anki.py has two functions under test in this file:
#   - _build_fields(card: ExportRequest) -> dict: pure- no network calls, no side effects. It
#     just formats an ExportRequest's eight fields into the {"Front": ..., "Back": ...} shape
#     that Anki's "Basic" note type expects, since "Basic" only has those two fields.
#   - export_card(card: ExportRequest, anki_note_id: int | None = None) -> int: builds an
#     AnkiConnect payload- "addNote" when anki_note_id is None (the default), "updateNoteFields"
#     targeting that note ID otherwise- POSTs it to ANKICONNECT_URL (backend.anki.requests.post),
#     and raises AnkiConnectError either if the POST itself fails outright (a network/connection
#     problem) or if AnkiConnect responds normally but with its own "error" field set in the
#     JSON body (e.g. a duplicate note). Returns the Anki note ID either way- addNote's own
#     assigned ID, or the same anki_note_id that was passed in for an update.
# Every test below that calls export_card patches "backend.anki.requests.post" so that no real
# network request is ever made- Anki desktop and AnkiConnect don't need to be running for
# these tests to pass, only the fake response object each test constructs matters.

# Values taken from the `sample_export_request` fixture in `conftest.py`-
# the following block of code ensures that `_build_fields` correctly folds the `ExportRequest`
# instance received from the frontend, derived from the LLM response in the form of a `CardDraft` object.
def test_build_fields_folds_card_into_front_and_back(sample_export_request):
    fields = _build_fields(sample_export_request)
    assert fields["Front"] == "大人"
    assert fields["Back"] == (
        "<b>Reading:</b> おとな<br>"
        "<b>Definition:</b> 成長した人。成人であること。<br>"
        "<b>Nuance:</b> 日常会話・フォーマルな場面どちらでも使える語。<br>"
        "<b>Synonyms:</b> 成人、大人物<br>"
        "<b>Antonyms:</b> 子供、未成年<br>"
        "<b>Example:</b> 彼はもう大人だ。<br>"
        "<b>JLPT:</b> N5"
    )
    # This test never touches requests.post at all- _build_fields does no I/O, so it can be
    # called directly and its return value checked, with no mocking needed.

# Checks the "happy path" of export_card: a mocked AnkiConnect response with a numeric
# "result" and no "error" should let export_card return normally, having actually called
# requests.post exactly once and having called .raise_for_status() on the response.
def test_export_card_succeeds(sample_export_request):
    mock_response = MagicMock()
    mock_response.json.return_value = {"result": 12345, "error": None}
    with patch("backend.anki.requests.post", return_value=mock_response) as mock_post:
        note_id = export_card(sample_export_request)
    assert note_id == 12345
    mock_post.assert_called_once()
    mock_response.raise_for_status.assert_called_once()
    # Patching "backend.anki.requests.post" (not just "requests.post") matters- it replaces
    # the `requests` reference as seen from inside backend/anki.py specifically, which is
    # where export_card's call actually happens. No anki_note_id passed in here, so this
    # exercises the addNote branch- the returned note_id should be AnkiConnect's own
    # "result" value, not the (absent) input.


def test_export_card_updates_existing_note_when_note_id_given(sample_export_request):
    mock_response = MagicMock()
    mock_response.json.return_value = {"result": None, "error": None}
    with patch("backend.anki.requests.post", return_value=mock_response) as mock_post:
        note_id = export_card(sample_export_request, anki_note_id=999)

    assert note_id == 999
    _, kwargs = mock_post.call_args
    payload = kwargs["json"]
    note = payload["params"]["note"]
    assert payload["action"] == "updateNoteFields"
    assert note["id"] == 999
    assert note["fields"]["Front"] == "大人"
    assert set(note.keys()) == {"id", "fields"}
    # Passing anki_note_id switches export_card to AnkiConnect's updateNoteFields action
    # instead of addNote- targeting the note by ID rather than creating a new one.
    # updateNoteFields' own "result" is null on success (see backend/anki.py)- it doesn't
    # hand back an ID, which is why export_card returns the *input* anki_note_id (999)
    # here rather than reading it from the response. The payload shape is also narrower
    # than addNote's- no deckName/modelName/options/tags, since those describe how to
    # create a note and don't apply to rewriting an existing one's fields.

# Checks *what* export_card actually sends to AnkiConnect, not just that it succeeds-
# inspecting mock_post.call_args lets this test look inside the JSON payload backend/anki.py
# built, confirming _build_fields' output and the "anki-tool-v2" tag both made it into the
# real request shape, without needing a real AnkiConnect server to receive it.
def test_export_card_sends_expected_payload(sample_export_request):
    mock_response = MagicMock()
    mock_response.json.return_value = {"result": 1, "error": None}
    with patch("backend.anki.requests.post", return_value=mock_response) as mock_post:
        export_card(sample_export_request)

    _, kwargs = mock_post.call_args
    note = kwargs["json"]["params"]["note"]
    assert note["fields"]["Front"] == "大人"
    assert note["tags"] == ["anki-tool-v2"]
    # mock_post.call_args is a (args, kwargs) pair recording exactly what export_card passed
    # to requests.post- since backend/anki.py calls
    # requests.post(ANKICONNECT_URL, json=payload, timeout=10), the payload dict is inside
    # kwargs["json"], not a positional argument.

# Simulates AnkiConnect responding successfully at the HTTP level (no exception, no
# raise_for_status failure) but reporting a logical failure in its own JSON body- e.g. Anki
# rejecting the note as a duplicate. backend/anki.py checks data.get("error") after the
# request succeeds and raises AnkiConnectError with that message if it's set.
def test_export_card_raises_on_anki_error(sample_export_request):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "result": None,
        "error": "cannot create note because it is a duplicate",
    }
    with patch("backend.anki.requests.post", return_value=mock_response):
        with pytest.raises(AnkiConnectError, match="duplicate"):
            export_card(sample_export_request)

# Simulates the other failure mode- AnkiConnect isn't reachable at all (e.g. Anki desktop
# isn't running), so requests.post itself raises rather than returning a response object.
# backend/anki.py wraps that call in a try/except requests.RequestException block and
# re-raises it as an AnkiConnectError with a clearer message, which is what this test checks.
def test_export_card_raises_when_anki_unreachable(sample_export_request):
    with patch(
        "backend.anki.requests.post", side_effect=requests.ConnectionError("refused")
    ):
        with pytest.raises(AnkiConnectError, match="Could not reach AnkiConnect"):
            export_card(sample_export_request)
