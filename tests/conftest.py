import pytest # Python test framework- includes reusable code for testing.
from fastapi.testclient import TestClient
# TestClient enables the sending of fake HTTP requests to a FastAPI app.
# TestClient "talks" to the FastAPI app the same way a request would.

from backend import llm
from backend.main import app
from backend.models import ExportRequest
# Import of key modules, objects and classes from backend scripts.

# conftest.py is a special filename that pytest recognizes automatically- it doesn't need to
# be imported by any test file. Any fixture defined in here becomes available to every test
# function anywhere in this directory, simply by naming it as a parameter, with no import
# statement needed in the test file itself.

@pytest.fixture # `@pytest.fixture` is a decorator function provided by the pytest framework.
# A decorator function takes a function and returns a wrapped or modified version of it.
def client():
    return TestClient(app)
# `app` here is the exact same FastAPI() instance defined in backend/main.py- the one that
# `uvicorn backend.main:app` runs in production. Wrapping it in TestClient lets test_main.py
# call client.post("/generate", ...) etc. and exercise the real routing/validation/exception
# logic in backend/main.py without starting a real server on a real port.

@pytest.fixture
def patch_api_key(monkeypatch):
    monkeypatch.setattr(llm, "API_KEY", "test-key")
    # `monkeypatch` is a small utility object with associated methods that allows for the
    # override of variables or attributes for the duration of a single test.
    # backend/llm.py reads OPENROUTER_API_KEY once at import time into a module-level
    # constant, llm.API_KEY. generate_card() raises LLMError immediately if that constant is
    # falsy- this fixture exists purely to get past that guard in tests, without needing a
    # real OPENROUTER_API_KEY set in the environment.


@pytest.fixture
def sample_card_json():
    return {
        "expression": "大人",
        "reading": "おとな",
        "definition_ja": "成長した人。成人であること。",
        "nuance": "日常会話・フォーマルな場面どちらでも使える語。",
        "synonyms": "成人、大人物",
        "antonyms": "子供、未成年",
        "example_sentence": "彼はもう大人だ。",
        "jlpt_level": "N5",
    }
# The keys here match backend/models.py's CardDraft field names exactly (expression, reading,
# definition_ja, nuance, synonyms, antonyms, example_sentence, jlpt_level)- this is the shape
# an OpenRouter response is expected to parse into. test_llm.py uses this dict to build fake
# LLM API responses (by JSON-encoding it into a mocked response's "content" field) rather than
# typing out the same eight fields by hand in every test.
# In Python, dicts or dictionaries are data structures that store info. in key-value pairs.


@pytest.fixture
def sample_export_request():
    return ExportRequest(
        expression="大人",
        reading="おとな",
        definition="成長した人。成人であること。",
        nuance="日常会話・フォーマルな場面どちらでも使える語。",
        synonyms="成人、大人物",
        antonyms="子供、未成年",
        example="彼はもう大人だ。",
        jlpt="N5",
    )
# Note most field names here differ from sample_card_json above (definition vs definition_ja,
# example vs example_sentence, jlpt vs jlpt_level)- that's backend/models.py's ExportRequest
# schema, the shape /export expects, as opposed to CardDraft, the shape /generate returns.
# synonyms/antonyms are the same on both sides (see backend/models.py's comment on why). This
# fixture is a real ExportRequest instance (not a plain dict), because test_anki.py's
# _build_fields() and export_card() both expect an actual ExportRequest object with attribute
# access (card.expression, card.reading, ...), not dictionary keys.
