import json
import time
from unittest.mock import ANY, MagicMock, patch

import pytest

from backend import llm
from backend.llm import (
    LLMError,
    generate_card,
    generate_card_plain,
    generate_card_with_events,
    generate_cards_batch,
)
from backend.models import BatchCardResult, CardDraft

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


def _make_llm_plain_response(card_json, *, omit_labels=()):
    lines = [
        f"{label.upper()}: {card_json[label]}"
        for label in [
            "expression", "reading", "definition_ja", "nuance",
            "synonyms", "antonyms", "example_sentence", "jlpt_level",
        ]
        if label not in omit_labels
    ]
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "\n".join(lines)}}]
    }
    return mock_response
# Same purpose as _make_llm_response above, but renders card_json into the plain
# "LABEL: value" line format generate_card_plain's prompt asks for (see
# backend/llm.py::_PROMPT_TEMPLATE_PLAIN/_parse_plain_card) instead of a JSON string.
# `omit_labels` lets a test drop one or more lines to exercise
# _parse_plain_card's missing-field check.


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


def test_generate_card_plain_returns_parsed_card(patch_api_key, sample_card_json):
    with patch(
        "backend.llm.requests.post",
        return_value=_make_llm_plain_response(sample_card_json),
    ):
        card = generate_card_plain("大人")
    assert card.expression == "大人"
    assert card.jlpt_level == "N5"
    # Happy path for plain mode, mirroring test_generate_card_returns_parsed_card above-
    # confirms _parse_plain_card successfully turns the labeled-line text back into a
    # CardDraft with all fields intact.


def test_generate_card_plain_retries_on_word_drift(patch_api_key, sample_card_json):
    wrong_word_card = {**sample_card_json, "expression": "猫"}
    responses = [
        _make_llm_plain_response(wrong_word_card),
        _make_llm_plain_response(sample_card_json),
    ]
    with patch("backend.llm.requests.post", side_effect=responses):
        card = generate_card_plain("大人")
    assert card.expression == "大人"


def test_generate_card_plain_raises_after_repeated_word_drift(patch_api_key, sample_card_json):
    wrong_word_card = {**sample_card_json, "expression": "猫"}
    responses = [
        _make_llm_plain_response(wrong_word_card),
        _make_llm_plain_response(wrong_word_card),
    ]
    with patch("backend.llm.requests.post", side_effect=responses):
        with pytest.raises(LLMError, match="kept substituting"):
            generate_card_plain("大人")


def test_generate_card_plain_wraps_request_errors(patch_api_key):
    with patch("backend.llm.requests.post", side_effect=Exception("network down")):
        with pytest.raises(LLMError, match="OpenRouter generation failed"):
            generate_card_plain("大人")


def test_generate_card_plain_raises_on_missing_labels(patch_api_key, sample_card_json):
    with patch(
        "backend.llm.requests.post",
        return_value=_make_llm_plain_response(sample_card_json, omit_labels=["nuance"]),
    ):
        with pytest.raises(LLMError, match="missing labeled field"):
            generate_card_plain("大人")
    # No structured-mode equivalent- CardDraft.model_validate_json already enforces every
    # field is present via pydantic, but plain mode's own _parse_plain_card has to check
    # this by hand since it's just splitting text on lines. Note this failure doesn't
    # retry (v1 scope, see backend/llm.py)- it raises LLMError on the first attempt.


def test_generate_card_plain_uses_level_in_prompt(patch_api_key, sample_card_json):
    with patch(
        "backend.llm.requests.post",
        return_value=_make_llm_plain_response(sample_card_json),
    ) as mock_post:
        generate_card_plain("大人", level="N1")
    sent_prompt = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "N1" in sent_prompt


def test_generate_card_plain_defaults_level_when_unspecified(patch_api_key, sample_card_json):
    with patch(
        "backend.llm.requests.post",
        return_value=_make_llm_plain_response(sample_card_json),
    ) as mock_post:
        generate_card_plain("大人")
    sent_prompt = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
    assert llm.JLPT_LEVEL_DEFAULT in sent_prompt


def test_generate_card_plain_omits_response_format(patch_api_key, sample_card_json):
    with patch(
        "backend.llm.requests.post",
        return_value=_make_llm_plain_response(sample_card_json),
    ) as mock_post:
        generate_card_plain("大人")
    assert "response_format" not in mock_post.call_args.kwargs["json"]
    # The entire point of plain mode- confirms _generate_card_via's `if response_format
    # is not None` branch actually leaves the key out of the request payload rather than
    # sending it as null, since omitting it is what skips OpenRouter's structured-output
    # path (see PROMPTS.md's Troubleshooting-motivated rationale).


def test_generate_cards_batch_uses_plain_mode(sample_card_json):
    card = CardDraft(**sample_card_json)
    with patch("backend.llm.generate_card_plain", return_value=card) as mock_plain, \
         patch("backend.llm.generate_card") as mock_structured:
        results = [r for r in generate_cards_batch(["大人"], mode="plain") if isinstance(r, BatchCardResult)]
    assert results[0].card.expression == "大人"
    mock_plain.assert_called_once_with("大人", level=llm.JLPT_LEVEL_DEFAULT, on_retry=ANY)
    mock_structured.assert_not_called()
    # Confirms generate_cards_batch's mode param actually selects generate_card_plain
    # instead of generate_card, rather than just accepting and ignoring the argument.
    # on_retry=ANY- generate_card_with_events always passes its own on_retry callback
    # through to generate_fn now (see backend/llm.py), so the exact callable isn't
    # something this test needs to pin down, just that *a* callback was passed.


def test_generate_cards_batch_continues_after_one_failure(sample_card_json):
    def fake_generate_card(word, level=None, on_retry=None):
        if word == "犬":
            raise LLMError("boom")
        return CardDraft(**{**sample_card_json, "expression": word})

    with patch("backend.llm.generate_card", side_effect=fake_generate_card):
        results = [r for r in generate_cards_batch(["大人", "犬"]) if isinstance(r, BatchCardResult)]
    # generate_cards_batch now yields zero or more heartbeat/retry progress dicts per word
    # (see generate_card_with_events in backend/llm.py) ahead of each word's terminal
    # BatchCardResult- filtering by isinstance keeps only those terminal results, same as
    # callers that want every finished word at once (rather than one progress tick at a
    # time, like backend/main.py's streaming route) would do. Both words here resolve
    # near-instantly (no real network call), so in practice no heartbeat ticks are emitted
    # anyway- this filter just keeps the test robust to timing.

    assert results[0].card.expression == "大人"
    assert results[0].error is None
    assert results[1].card is None
    assert results[1].error == "boom"


def test_generate_card_with_events_fast_success_has_no_heartbeats(sample_card_json):
    card = CardDraft(**sample_card_json)
    with patch("backend.llm.generate_card", return_value=card):
        events = list(generate_card_with_events("大人"))
    assert [e["event"] for e in events] == ["result"]
    assert events[-1]["card"]["expression"] == "大人"
    # A call that resolves near-instantly (well under HEARTBEAT_INTERVAL_S) should produce
    # zero heartbeat events- just the terminal "result", same as generate_card's own return
    # value converted to an event.


def test_generate_card_with_events_emits_heartbeat_for_slow_call(
    monkeypatch, sample_card_json
):
    monkeypatch.setattr(llm, "HEARTBEAT_INTERVAL_S", 0.01)
    monkeypatch.setattr(llm, "_QUEUE_POLL_S", 0.002)
    card = CardDraft(**sample_card_json)

    def slow_generate_card(word, level=None, on_retry=None):
        time.sleep(0.05)
        return card

    with patch("backend.llm.generate_card", side_effect=slow_generate_card):
        events = list(generate_card_with_events("大人"))
    assert events[0]["event"] == "heartbeat"
    assert events[-1]["event"] == "result"
    # HEARTBEAT_INTERVAL_S/_QUEUE_POLL_S are monkeypatched down so the test doesn't have to
    # wait out the real ~2.5s interval- the mocked call still takes ~0.05s (real time.sleep,
    # not mocked), long enough to cross several heartbeat ticks at this interval.


def test_generate_card_with_events_emits_retry_before_result(sample_card_json):
    card = CardDraft(**sample_card_json)

    def generate_card_that_retries(word, level=None, on_retry=None):
        if on_retry is not None:
            on_retry()
        return card

    with patch("backend.llm.generate_card", side_effect=generate_card_that_retries):
        events = list(generate_card_with_events("大人"))
    assert [e["event"] for e in events] == ["retry", "result"]
    # Simulates _generate_card_via firing on_retry before returning (see backend/llm.py)-
    # generate_card_with_events should surface that as its own "retry" event ahead of the
    # terminal "result", not only via a heartbeat tick that might not land in time.


def test_generate_card_with_events_reports_llm_error():
    with patch("backend.llm.generate_card", side_effect=LLMError("boom")):
        events = list(generate_card_with_events("大人"))
    assert events == [{"event": "error", "detail": "boom"}]
    # A generation failure (LLMError, the only exception type generate_card/
    # generate_card_plain themselves raise) must become a terminal "error" event instead of
    # propagating out of this generator- callers (backend/main.py's streaming routes) rely
    # on that to keep the HTTP response at 200 with the failure reported in-band.


def test_generate_card_with_events_reports_unexpected_error():
    with patch("backend.llm.generate_card", side_effect=ValueError("kaboom")):
        events = list(generate_card_with_events("大人"))
    assert events[-1]["event"] == "error"
    assert "kaboom" in events[-1]["detail"]
    # Any exception type, not just LLMError, must still resolve to an "error" event rather
    # than raising out of the generator- future.result() re-raises whatever exception ran
    # inside the worker thread, and the broad `except Exception` here is what catches it.
    # This test patches generate_card itself, not requests.post- generate_cards_batch calls
    # generate_card_with_events, which calls generate_card, another function in the *same*
    # module (backend/llm.py), so that's the right boundary to mock here. side_effect set to
    # a callable function (rather than a list or single exception) lets the mock behave
    # differently per word: succeed for "大人", raise for "犬"- matching
    # generate_card_with_events turning that LLMError into a terminal "error" event, which
    # becomes this BatchCardResult's `error` field, without aborting the rest of the batch.
