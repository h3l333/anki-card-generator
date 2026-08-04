import os
# Reads OPENROUTER_API_KEY / OPENROUTER_MODELS from the environment below- see README
# Configuration for what each one does and its default.

import requests
# The HTTP client used to call OpenRouter directly- there's no official OpenRouter SDK
# in use here, just a plain POST built by hand (see generate_card below).

from backend.models import BatchCardResult, CardDraft

API_KEY = os.getenv("OPENROUTER_API_KEY")
# No default- an unset key should fail loudly (see the guard clause in generate_card
# below) rather than the app silently trying to authenticate with an empty string.

DEFAULT_MODELS = "google/gemma-4-26b-a4b-it:free,openai/gpt-oss-20b:free,nvidia/nemotron-3-super-120b-a12b:free"
# A single comma-separated string, not a Python list- this is so it matches the exact
# format OPENROUTER_MODELS is expected to be supplied in as an environment variable
# (env vars are always plain strings), letting the same parsing line below handle both
# the default and a user-supplied override identically.

MODEL_NAMES = [
    m.strip() for m in os.getenv("OPENROUTER_MODELS", DEFAULT_MODELS).split(",") if m.strip()
]
# Splits that comma-separated string into a list, trims whitespace around each entry
# (in case someone writes "model-a, model-b" with a space after the comma), and drops
# any empty strings that would result from a stray trailing comma. The end result is
# what gets sent to OpenRouter as its native `models` array in generate_card below- see
# PROMPTS.md's change log for why this is a list handled by OpenRouter itself, rather
# than a single model with a retry loop written in this file.

API_URL = "https://openrouter.ai/api/v1/chat/completions"
# OpenRouter's chat-completions endpoint- OpenAI-compatible in shape, which is why the
# request body below (a "messages" list with role/content) looks like a typical chat
# API call rather than anything custom to OpenRouter.

_PROMPT_TEMPLATE = """\
対象語: 「{word}」

あなたは日本語学習者(中級〜上級)向けの辞書カードを作成します。
必ず「{word}」についてのみ回答してください。他の単語やより一般的な例に置き換えないでください。

次の情報をJSON形式で生成してください:
- expression: 「{word}」の表記(漢字・かな)
- reading: 「{word}」のひらがなでの読み方
- definition_ja: 「{word}」の日本語のみによる定義(モノリンガル)
- nuance: 「{word}」の使い方のニュアンス、フォーマル度、類似語との違いなどの説明
- example_sentence: 「{word}」を使った自然な例文。ふりがなは付けず、漢字とかなのみのプレーンテキストで書いてください。
- jlpt_level: 「{word}」の推定されるJLPTレベル(N5〜N1のいずれか)

繰り返しますが、対象語は「{word}」です。
"""
# `"""\` immediately followed by a newline starts a triple-quoted string without that
# first newline becoming part of the string itself (the backslash escapes it away)- so
# the string starts right at "対象語:" instead of with a blank first line. `{word}` is a
# str.format() placeholder, filled in via _PROMPT_TEMPLATE.format(word=word) further
# down- notice the target word is repeated at the start, middle, and end of the prompt
# on purpose (see PROMPTS.md's change log): that repetition was added specifically to
# fight cloud/local models drifting onto a different, more common word mid-generation.


class LLMError(Exception):
    """Raised when the LLM API is unreachable, misconfigured, or returns a response that doesn't match the schema."""
    # Triple quotes in Python allow for the creation of multi-line strings and docstrings.

def generate_card(word: str) -> CardDraft:
    if not API_KEY:
        raise LLMError("OPENROUTER_API_KEY is not set - see README.md Configuration.")
    # Checked first and separately from the try/except below- a missing key is a
    # configuration problem, not a network failure, so it's worth its own clear message
    # rather than being wrapped in the generic "OpenRouter generation failed" text below.

    card = None
    for _attempt in range(2):
        # Up to two attempts total- see the word-drift check near the bottom of this
        # loop for what triggers a second attempt, and the final raise after the loop
        # for what happens if both attempts still get it wrong. `_attempt` itself is
        # never used inside the loop body (the leading underscore is a convention
        # signaling "this loop variable is intentionally unused")- only the fact that
        # the loop runs at most twice matters here.
        try:
            response = requests.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "models": MODEL_NAMES,
                    "messages": [
                        {"role": "user", "content": _PROMPT_TEMPLATE.format(word=word)}
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "CardDraft",
                            "strict": True,
                            "schema": CardDraft.model_json_schema(),
                        },
                    },
                },
                timeout=60,
            )
            # "models" (plural, a list) is OpenRouter's own extension over the usual
            # single "model" field- OpenRouter tries each entry in MODEL_NAMES in order
            # server-side, falling through to the next one if a given model is
            # rate-limited or no longer free, so no retry loop for *that* is needed here.
            # "response_format"/"json_schema" is OpenRouter's structured-output feature-
            # passing CardDraft.model_json_schema() (a plain dict describing CardDraft's
            # fields and their descriptions) tells the model to return JSON matching
            # that exact shape, with "strict": True making the model provider enforce it
            # rather than just hint at it in the prompt.
            response.raise_for_status()
            # Raises requests.HTTPError if OpenRouter responded with a 4xx/5xx status-
            # caught by the broad `except Exception` below, same as every other failure
            # in this block.
            content = response.json()["choices"][0]["message"]["content"]
            # OpenRouter's response shape mirrors the OpenAI chat-completions format:
            # a "choices" list (only the first choice is used here) containing a
            # "message" with a "content" string- that string is itself JSON text (per
            # the response_format above), not yet a CardDraft object.
            card = CardDraft.model_validate_json(content)
            # Parses that JSON string directly into a validated CardDraft instance in
            # one step- if `content` is malformed JSON, or missing a required field,
            # or has a field of the wrong type, this line itself raises, which is why
            # it's still inside this try block.
        except Exception as exc:
            raise LLMError(f"OpenRouter generation failed for '{word}': {exc}") from exc
        # A single broad `except Exception` covers every failure mode above at once
        # (network error, HTTP error status, malformed JSON, schema mismatch)- they all
        # get wrapped into the same LLMError type with a word-specific message, so
        # callers (backend/main.py, generate_cards_batch below) only ever need to
        # handle one exception type regardless of which step actually failed.

        # Cloud models can also drift onto a different word - catch that
        # instead of silently returning a card for the wrong term.
        if word in card.expression:
            return card
        # `word in card.expression` is a substring check, not an equality check- e.g.
        # requesting "大人" would also accept an expression of "大人しい" if that ever
        # happened, since the substring is present either way. If this check fails, the
        # loop simply continues to its next iteration (a second, fresh API call)
        # instead of returning- there's no `else` needed since `return` above already
        # exits the function on success.

    raise LLMError(
        f"Model kept substituting a different word instead of '{word}' "
        f"(got '{card.expression}') after retrying"
    )
    # Only reached if the loop above completed both iterations without ever hitting the
    # `return card` line- i.e. both attempts drifted to the wrong word. `card` here is
    # still bound to whatever the second (most recent) attempt produced, since Python
    # doesn't scope loop-body variables to the loop itself.


def generate_cards_batch(words: list[str]) -> list[BatchCardResult]:
    results = []
    for word in words:
        try:
            results.append(BatchCardResult(word=word, card=generate_card(word)))
        except LLMError as exc:
            results.append(BatchCardResult(word=word, error=str(exc)))
    return results
    # Each word gets its own try/except, rather than one try/except wrapping the whole
    # loop- this is what lets one bad word (rate limit, persistent word drift, whatever
    # triggered the LLMError) skip past without aborting the batch or losing results
    # already generated for earlier words. The BatchCardResult for a failed word carries
    # `error=str(exc)` and leaves `card` at its default of None; a succeeded word is the
    # reverse- see backend/models.py's BatchCardResult for why those two fields are
    # meant to be mutually exclusive.
