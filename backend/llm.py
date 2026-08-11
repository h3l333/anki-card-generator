import os
# Reads OPENROUTER_API_KEY / OPENROUTER_MODELS from the environment below- see README
# Configuration for what each one does and its default.

from collections.abc import Iterator
# Return-type annotation for generate_cards_batch below- it's a generator function
# (built on `yield`, not `return`), and Iterator is the general type for "something
# you can loop over once with next()", which is what a generator actually is at runtime.

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

JLPT_LEVEL_DEFAULT = os.getenv("JLPT_LEVEL_DEFAULT", "N3")
# Target-audience level: what learner level definition_ja/nuance/example_sentence
# should be written for, distinct from CardDraft.jlpt_level (the model's own estimate
# of the target *word's* difficulty). Same env-var-with-default pattern as MODEL_NAMES
# above; the frontend's level dropdown sends its own value on every request, so this
# only matters when the frontend doesn't (GenerateRequest.level/BatchGenerateRequest.level
# left unset).

_PROMPT_TEMPLATE = """\
対象語: 「{word}」
想定読者のレベル: JLPT {level}

あなたは日本語学習者向けの辞書カードを作成します。
必ず「{word}」についてのみ回答してください。他の単語やより一般的な例に置き換えないでください。
definition_ja、nuance、example_sentenceは、JLPT {level}の学習者が理解できる語彙と文法だけを使って書いてください。

次の情報をJSON形式で生成してください:
- expression: 「{word}」の表記(漢字・かな)
- reading: 「{word}」のひらがなでの読み方
- definition_ja: 「{word}」の日本語のみによる定義(モノリンガル)。JLPT {level}レベル向け。
- nuance: 「{word}」の使い方のニュアンス、フォーマル度、類似語との違いなどの説明。JLPT {level}レベル向け。
- synonyms: 「{word}」の類義語(似た意味を持つ語)。読点で区切って複数挙げてください。該当するものがなければ「該当なし」と書いてください。
- antonyms: 「{word}」の対義語(反対の意味を持つ語)。読点で区切って複数挙げてください。該当するものがなければ「該当なし」と書いてください。
- example_sentence: 「{word}」を使った自然な例文。JLPT {level}レベルの学習者向けに、ふりがなは付けず、漢字とかなのみのプレーンテキストで書いてください。
- jlpt_level: 「{word}」の推定されるJLPTレベル(N5〜N1のいずれか)。これは対象語自体の難易度であり、上記の想定読者レベルとは別物です。

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

def generate_card(word: str, level: str = JLPT_LEVEL_DEFAULT) -> CardDraft:
    if not API_KEY:
        raise LLMError("OPENROUTER_API_KEY is not set- see README.md Configuration.")
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
                        {
                            "role": "user",
                            "content": _PROMPT_TEMPLATE.format(word=word, level=level),
                        }
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
                timeout=180,
            )
            # 180s (was 60s)- structured-output requests under a strict JSON schema can
            # take a lot longer than a plain chat reply if the model does heavy internal
            # reasoning before emitting the final JSON (observed directly against
            # OpenRouter- see PROMPTS.md change log). Note this is still a *per-read*
            # timeout, not a wall-clock one (requests' timeout resets on every byte
            # received, including keep-alive padding)- raising the number gives a slow-
            # but-finite generation more room, but doesn't cap a generation that never
            # stops. With the retry loop above, a single generate_card() call can now
            # take up to ~360s worst case (two attempts).
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

        # Cloud models can also drift onto a different word- catch that
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


def generate_cards_batch(
    words: list[str], level: str = JLPT_LEVEL_DEFAULT
) -> Iterator[BatchCardResult]:
    for word in words:
        try:
            yield BatchCardResult(word=word, card=generate_card(word, level=level))
        except LLMError as exc:
            yield BatchCardResult(word=word, error=str(exc))
    # A generator rather than building and returning a list- backend/main.py's
    # /generate/batch route streams one result at a time to the frontend as each word
    # finishes (see _stream_batch_results there), so nothing should call generate_card for
    # word N+1 before word N's result has already been handed back to the caller. Each
    # word still gets its own try/except, rather than one try/except wrapping the whole
    # loop- this is what lets one bad word (rate limit, persistent word drift, whatever
    # triggered the LLMError) skip past without aborting the batch or losing results
    # already generated for earlier words. The BatchCardResult for a failed word carries
    # `error=str(exc)` and leaves `card` at its default of None; a succeeded word is the
    # reverse- see backend/models.py's BatchCardResult for why those two fields are
    # meant to be mutually exclusive.
    # Calling this with an empty `words` list yields zero times- fine, since the only
    # caller (backend/main.py) only ever iterates it in lockstep with a matching number
    # of pending slots.
