import json
from unittest.mock import MagicMock, patch

import pytest

from backend import llm
from backend.llm import LLMError, generate_card, generate_cards_batch
from backend.models import CardDraft

# backend/llm.py has two functions under test in this file:
#   - generate_card(word: str) -> CardDraft: POSTs a prompt to OpenRouter
#     (backend.llm.requests.post), asks it for a JSON body matching CardDraft's schema, and
#     parses response["choices"][0]["message"]["content"] with CardDraft.model_validate_json().
#     It retries once (2 attempts total) if the returned card's expression doesn't contain the
#     requested word- cloud models can occasionally drift onto an unrelated word- and raises
#     LLMError if OPENROUTER_API_KEY isn't set, if requests.post/parsing fails for any reason,
#     or if both attempts keep drifting off the requested word.
#   - generate_cards_batch(words: list[str]) -> Iterator[BatchCardResult]: a generator that
#     loops generate_card over a list of words, catching LLMError per word rather than
#     failing the whole batch, so one bad word doesn't prevent the rest from generating.
# Every test that calls generate_card patches "backend.llm.requests.post" so no real network
# call to OpenRouter is ever made- no OPENROUTER_API_KEY or internet connection is required for
# these tests to pass, only the fake response object each test builds matters.


def _make_llm_response(card_json):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": json.dumps(card_json)}}]
    }
    return mock_response
# A small helper function (not a fixture, since it needs a different card_json per test) that
# mimics the shape of a real OpenRouter chat-completion response. Note json.dumps(card_json)-
# the "content" field has to be an actual JSON *string*, not a Python dict, because that's
# exactly what generate_card hands to CardDraft.model_validate_json(content) in backend/llm.py.


def test_generate_card_raises_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(llm, "API_KEY", None)
    with pytest.raises(LLMError, match="OPENROUTER_API_KEY is not set"):
        generate_card("大人")
    # This bypasses requests.post entirely- backend/llm.py checks `if not API_KEY` as its very
    # first line and raises immediately, so no mocking of the network call is even needed here.


def test_generate_card_returns_parsed_card(patch_api_key, sample_card_json):
    with patch(
        "backend.llm.requests.post", return_value=_make_llm_response(sample_card_json)
    ):
        card = generate_card("大人")
    assert card.expression == "大人"
    assert card.jlpt_level == "N5"
    # The "happy path"- word matches the mocked response's expression on the very first
    # attempt, so generate_card returns a real CardDraft instance without needing to retry.


def test_generate_card_retries_on_word_drift(patch_api_key, sample_card_json):
    wrong_word_card = {**sample_card_json, "expression": "猫"}
    responses = [_make_llm_response(wrong_word_card), _make_llm_response(sample_card_json)]
    with patch("backend.llm.requests.post", side_effect=responses):
        card = generate_card("大人")
    assert card.expression == "大人"
    # side_effect set to a *list* makes the mock return each item in order across successive
    # calls- the first requests.post call comes back with the wrong word ("猫" instead of
    # "大人"), matching backend/llm.py's retry loop's first iteration failing the
    # `if word in card.expression` check, then the second call returns the correct word and
    # the loop returns successfully on its second (final) attempt.


def test_generate_card_raises_after_repeated_word_drift(patch_api_key, sample_card_json):
    wrong_word_card = {**sample_card_json, "expression": "猫"}
    responses = [_make_llm_response(wrong_word_card), _make_llm_response(wrong_word_card)]
    with patch("backend.llm.requests.post", side_effect=responses):
        with pytest.raises(LLMError, match="kept substituting"):
            generate_card("大人")
    # Both attempts drift to the wrong word this time, so the retry loop in backend/llm.py
    # exhausts both iterations and falls through to the final `raise LLMError(...)` after the
    # loop- the "kept substituting" text comes straight from that message.


def test_generate_card_wraps_request_errors(patch_api_key):
    with patch("backend.llm.requests.post", side_effect=Exception("network down")):
        with pytest.raises(LLMError, match="OpenRouter generation failed"):
            generate_card("大人")
    # Here side_effect is a single exception instance (not a list)- the mock raises it every
    # time it's called instead of returning a value. backend/llm.py's `except Exception as exc`
    # block catches this exact scenario (a request that fails outright) and re-raises it as an
    # LLMError with a clearer, word-specific message.


def test_generate_card_uses_level_in_prompt(patch_api_key, sample_card_json):
    with patch(
        "backend.llm.requests.post", return_value=_make_llm_response(sample_card_json)
    ) as mock_post:
        generate_card("大人", level="N1")
    sent_prompt = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "N1" in sent_prompt
    # Confirms `level` actually reaches the prompt sent to OpenRouter, not just that
    # generate_card() accepts the parameter- the prompt template's {level} slot
    # (backend/llm.py::_PROMPT_TEMPLATE) is what backend/main.py relies on to cater
    # definition_ja/nuance/example_sentence to the requester's chosen JLPT level.


def test_generate_card_defaults_level_when_unspecified(patch_api_key, sample_card_json):
    with patch(
        "backend.llm.requests.post", return_value=_make_llm_response(sample_card_json)
    ) as mock_post:
        generate_card("大人")
    sent_prompt = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
    assert llm.JLPT_LEVEL_DEFAULT in sent_prompt
    # No level passed- generate_card()'s own default parameter (JLPT_LEVEL_DEFAULT) should
    # be what lands in the prompt, same fallback backend/main.py relies on when a request
    # omits GenerateRequest.level/BatchGenerateRequest.level.


def test_generate_cards_batch_continues_after_one_failure(sample_card_json):
    def fake_generate_card(word, level=None):
        if word == "犬":
            raise LLMError("boom")
        return CardDraft(**{**sample_card_json, "expression": word})

    with patch("backend.llm.generate_card", side_effect=fake_generate_card):
        results = list(generate_cards_batch(["大人", "犬"]))
    # generate_cards_batch is a generator (see backend/llm.py)- list(...) drains it into
    # a plain list so it can be indexed below, same as callers that want every result at
    # once (rather than one at a time, like backend/main.py's streaming route) would do.

    assert results[0].card.expression == "大人"
    assert results[0].error is None
    assert results[1].card is None
    assert results[1].error == "boom"
    # This test patches generate_card itself, not requests.post- generate_cards_batch calls
    # another function in the *same* module (backend/llm.py), so that's the right boundary to
    # mock here. side_effect set to a callable function (rather than a list or single
    # exception) lets the mock behave differently per word: succeed for "大人", raise for
    # "犬"- matching backend/llm.py's per-word try/except that's supposed to let one bad word
    # skip without losing the rest of the batch.
