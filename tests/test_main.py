from unittest.mock import patch

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


def test_generate_route_returns_card(client, sample_card_json):
    card = CardDraft(**sample_card_json)
    with patch("backend.main.generate_card", return_value=card):
        response = client.post("/generate", json={"word": "大人"})
    assert response.status_code == 200
    assert response.json()["expression"] == "大人"
    # `client` comes from the `client` fixture in conftest.py- a TestClient wrapping the real
    # FastAPI() app object from backend/main.py. Posting to "/generate" runs backend/main.py's
    # actual generate() route function in-process; only generate_card underneath it is mocked.


def test_generate_route_maps_llm_error_to_502(client):
    with patch("backend.main.generate_card", side_effect=LLMError("boom")):
        response = client.post("/generate", json={"word": "大人"})
    assert response.status_code == 502
    assert response.json()["detail"] == "boom"
    # backend/main.py's generate() route catches LLMError specifically and re-raises it as
    # HTTPException(status_code=502, detail=str(exc))- this checks that mapping directly.


def test_generate_batch_route_returns_results(client, sample_card_json):
    card = CardDraft(**sample_card_json)
    results = [BatchCardResult(word="大人", card=card)]
    with (
        patch("backend.main.parse_and_validate", return_value=["大人"]),
        patch("backend.main.generate_cards_batch", return_value=results),
    ):
        response = client.post("/generate/batch", json={"file_content": "大人"})
    assert response.status_code == 200
    assert response.json()["results"][0]["word"] == "大人"
    # /generate/batch calls two backend functions in sequence (parse_and_validate, then
    # generate_cards_batch)- both need mocking here since this test is only about the route's
    # wiring, not either function's own internal logic. Python lets multiple context managers
    # be combined in one `with (...)` block using parentheses, instead of nesting or using a
    # backslash line continuation.


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
    with patch("backend.main.export_card", return_value=None):
        response = client.post("/export", json=sample_export_request.model_dump())
    assert response.status_code == 200
    assert response.json() == {"status": "exported"}
    # sample_export_request (from conftest.py) is a real ExportRequest object, but
    # client.post(json=...) needs a plain dict to serialize into the request body-
    # .model_dump() converts the Pydantic model back into one. export_card returning None here
    # mirrors its real signature (-> None)- the route itself builds the response body.


def test_export_route_maps_anki_error_to_503(client, sample_export_request):
    with patch("backend.main.export_card", side_effect=AnkiConnectError("unreachable")):
        response = client.post("/export", json=sample_export_request.model_dump())
    assert response.status_code == 503
    assert response.json()["detail"] == "unreachable"
    # backend/main.py's export() route catches AnkiConnectError specifically and re-raises it
    # as HTTPException(status_code=503, detail=str(exc))- this checks that final mapping.
