import os
# Reads OPENROUTER_API_KEY / OPENROUTER_MODELS from the environment below- see README
# Configuration for what each one does and its default.

from collections.abc import Callable, Iterator
# Iterator is the return-type annotation for generate_cards_batch below- it's a
# generator function (built on `yield`, not `return`), and Iterator is the general type
# for "something you can loop over once with next()", which is what a generator
# actually is at runtime. Callable annotates the `parse` argument _generate_card_via
# takes below- either CardDraft.model_validate_json or _parse_plain_card, both of which
# are "a function from str to CardDraft".

import queue
import re
# Used by _parse_plain_card below to split each line of a plain-text LLM response on
# its label/value separator.

import time
from concurrent.futures import ThreadPoolExecutor

import requests
# The HTTP client used to call OpenRouter directly- there's no official OpenRouter SDK
# in use here, just a plain POST built by hand (see _generate_card_via below).

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

_EXECUTOR = ThreadPoolExecutor(max_workers=4)
# Runs the blocking generate_card/generate_card_plain call off the request-handling
# thread so generate_card_with_events below can yield heartbeat lines while it's still
# in flight. 4 workers is headroom for this single-user local tool (one /generate call
# plus one in-flight batch word, plus slack for e.g. a stray double-click)- not meant
# to be tuned further.

HEARTBEAT_INTERVAL_S = 2.5
# How often generate_card_with_events yields a heartbeat event while waiting on the
# background generation call.

_QUEUE_POLL_S = 0.2
# How often generate_card_with_events polls the retry-signal queue/future while
# waiting- short enough that a retry event surfaces promptly without busy-waiting.

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

_PROMPT_TEMPLATE_PLAIN = """\
対象語: 「{word}」
想定読者のレベル: JLPT {level}

あなたは日本語学習者向けの辞書カードを作成します。
必ず「{word}」についてのみ回答してください。他の単語やより一般的な例に置き換えないでください。
definition_ja、nuance、example_sentenceは、JLPT {level}の学習者が理解できる語彙と文法だけを使って書いてください。

次の8項目を、必ず英大文字のラベルで始まる1行ずつの形式で出力してください。
ラベルの直後にコロン(:)、半角スペース、続けて値のみを同じ行に書いてください。
マークダウンの見出しや箇条書き記号(-、*、#など)、番号付けは使わないでください。
各項目の値は改行を含めず1行に収めてください。ラベルと値の8行以外は一切出力しないでください(前置きや説明文も禁止)。

EXPRESSION: 「{word}」の表記(漢字・かな)
READING: 「{word}」のひらがなでの読み方
DEFINITION_JA: 「{word}」の日本語のみによる定義(モノリンガル)。JLPT {level}レベル向け。
NUANCE: 「{word}」の使い方のニュアンス、フォーマル度、類似語との違いなど。JLPT {level}レベル向け。
SYNONYMS: 「{word}」の類義語。読点で区切って複数挙げる。該当するものがなければ「該当なし」。
ANTONYMS: 「{word}」の対義語。読点で区切って複数挙げる。該当するものがなければ「該当なし」。
EXAMPLE_SENTENCE: 「{word}」を使った自然な例文。ふりがなは付けず、漢字とかなのみのプレーンテキスト。
JLPT_LEVEL: 「{word}」の推定JLPTレベル(N5〜N1のいずれか一つ)。

繰り返しますが、対象語は「{word}」です。出力は上記8行のみで、それ以外の文章は一切含めないでください。
"""
# Used by generate_card_plain instead of _PROMPT_TEMPLATE above when the caller asked
# for plain-text mode (see backend/models.py's GenMode)- skips json_schema/response_format
# entirely (see PROMPTS.md's Troubleshooting-motivated rationale) in favor of asking the
# model for 8 plain "LABEL: value" lines. The labels are deliberately the same 8 names
# as CardDraft's fields, uppercased- that's what lets _parse_plain_card below build a
# dict and hand it straight to CardDraft(**fields) with no separate label-to-field
# mapping table to keep in sync if a field is ever renamed.

_PLAIN_LABELS = [
    "EXPRESSION",
    "READING",
    "DEFINITION_JA",
    "NUANCE",
    "SYNONYMS",
    "ANTONYMS",
    "EXAMPLE_SENTENCE",
    "JLPT_LEVEL",
]


def _parse_plain_card(text: str) -> CardDraft:
    fields: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-*•\t ")
        if not line or (":" not in line and "：" not in line):
            continue
        label, value = re.split(r"[:：]", line, maxsplit=1)
        label = label.strip().upper()
        if label in _PLAIN_LABELS:
            fields[label.lower()] = value.strip()
    # Tolerant of stray bullet markers (-/*/•) or a leading tab/space before a label,
    # and of either a half-width or full-width colon after it- but not of a label being
    # reworded, translated, or split across multiple lines, since matching depends on
    # the exact uppercase label text from _PROMPT_TEMPLATE_PLAIN above. A line that
    # doesn't start with a recognized label (e.g. stray prose the model added despite
    # being told not to) is silently skipped rather than raising- only a genuinely
    # *missing* label is treated as a failure, checked below.

    missing = [label for label in _PLAIN_LABELS if label.lower() not in fields]
    if missing:
        raise ValueError(
            f"plain-text response missing labeled field(s): {', '.join(missing)}"
        )
    return CardDraft(**fields)
    # No retry-on-parse-failure here (v1 scope)- this raises straight into
    # _generate_card_via's `except Exception`, which wraps it into the same LLMError
    # every other failure mode produces. A future revision could give parse failures
    # their own retry, separate from the word-drift retry below, once real plain-mode
    # model output has been observed.


class LLMError(Exception):
    """Raised when the LLM API is unreachable, misconfigured, or returns a response that doesn't match the schema."""
    # Triple quotes in Python allow for the creation of multi-line strings and docstrings.

def _generate_card_via(
    word: str,
    level: str,
    *,
    prompt_template: str,
    response_format: dict | None,
    parse: Callable[[str], CardDraft],
    on_retry: Callable[[], None] | None = None,
) -> CardDraft:
    # Shared by generate_card and generate_card_plain below- the two differ only in
    # which prompt template is sent, whether response_format is attached at all, and
    # how the raw response text is turned into a CardDraft, so those three things are
    # exactly what's parameterized here rather than duplicating the request/retry loop
    # itself in both functions.
    if not API_KEY:
        raise LLMError("OPENROUTER_API_KEY is not set- see README.md Configuration.")
    # Checked first and separately from the try/except below- a missing key is a
    # configuration problem, not a network failure, so it's worth its own clear message
    # rather than being wrapped in the generic "OpenRouter generation failed" text below.

    card = None
    for attempt_index in range(2):
        # Up to two attempts total- see the word-drift check near the bottom of this
        # loop for what triggers a second attempt, and the final raise after the loop
        # for what happens if both attempts still get it wrong. attempt_index is used
        # below to fire on_retry exactly once, the moment a second attempt is decided.
        try:
            payload = {
                "models": MODEL_NAMES,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt_template.format(word=word, level=level),
                    }
                ],
            }
            if response_format is not None:
                payload["response_format"] = response_format
            # generate_card_plain passes response_format=None- omitting the key entirely
            # (rather than sending it as null) is what actually skips OpenRouter's
            # structured-output path, which is the whole point of plain-text mode (see
            # PROMPTS.md's Troubleshooting-motivated rationale for why that's faster).
            response = requests.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=180,
            )
            # 180s (was 60s)- structured-output requests under a strict JSON schema can
            # take a lot longer than a plain chat reply if the model does heavy internal
            # reasoning before emitting the final JSON (observed directly against
            # OpenRouter- see PROMPTS.md change log). Note this is still a *per-read*
            # timeout, not a wall-clock one (requests' timeout resets on every byte
            # received, including keep-alive padding)- raising the number gives a slow-
            # but-finite generation more room, but doesn't cap a generation that never
            # stops. With the retry loop above, a single call can now take up to ~360s
            # worst case (two attempts).
            # "models" (plural, a list) is OpenRouter's own extension over the usual
            # single "model" field- OpenRouter tries each entry in MODEL_NAMES in order
            # server-side, falling through to the next one if a given model is
            # rate-limited or no longer free, so no retry loop for *that* is needed here.
            response.raise_for_status()
            # Raises requests.HTTPError if OpenRouter responded with a 4xx/5xx status-
            # caught by the broad `except Exception` below, same as every other failure
            # in this block.
            content = response.json()["choices"][0]["message"]["content"]
            # OpenRouter's response shape mirrors the OpenAI chat-completions format:
            # a "choices" list (only the first choice is used here) containing a
            # "message" with a "content" string. For structured mode that string is
            # itself JSON text (per response_format above); for plain mode it's the raw
            # "LABEL: value" lines _parse_plain_card expects- either way it's `parse`'s
            # job to turn it into a CardDraft, not this function's.
            card = parse(content)
            # For generate_card this is CardDraft.model_validate_json (parses+validates
            # JSON text in one step); for generate_card_plain this is _parse_plain_card
            # above. If `content` doesn't match what `parse` expects (malformed JSON,
            # missing a required field, or- for plain mode- a missing labeled line),
            # this line itself raises, which is why it's still inside this try block.
        except Exception as exc:
            raise LLMError(f"OpenRouter generation failed for '{word}': {exc}") from exc
        # A single broad `except Exception` covers every failure mode above at once
        # (network error, HTTP error status, malformed/mismatched response)- they all
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

        if attempt_index == 0 and on_retry is not None:
            on_retry()
        # Fires the instant the retry is decided- before attempt 2's requests.post is
        # even issued- so a caller polling for progress (generate_card_with_events
        # below) can surface "retrying" immediately rather than waiting for the next
        # heartbeat tick.

    raise LLMError(
        f"Model kept substituting a different word instead of '{word}' "
        f"(got '{card.expression}') after retrying"
    )
    # Only reached if the loop above completed both iterations without ever hitting the
    # `return card` line- i.e. both attempts drifted to the wrong word. `card` here is
    # still bound to whatever the second (most recent) attempt produced, since Python
    # doesn't scope loop-body variables to the loop itself.


def generate_card(
    word: str,
    level: str = JLPT_LEVEL_DEFAULT,
    on_retry: Callable[[], None] | None = None,
) -> CardDraft:
    return _generate_card_via(
        word,
        level,
        prompt_template=_PROMPT_TEMPLATE,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "CardDraft",
                "strict": True,
                "schema": CardDraft.model_json_schema(),
            },
        },
        parse=CardDraft.model_validate_json,
        on_retry=on_retry,
    )
    # "response_format"/"json_schema" is OpenRouter's structured-output feature-
    # passing CardDraft.model_json_schema() (a plain dict describing CardDraft's fields
    # and their descriptions) tells the model to return JSON matching that exact shape,
    # with "strict": True making the model provider enforce it rather than just hint at
    # it in the prompt.


def generate_card_plain(
    word: str,
    level: str = JLPT_LEVEL_DEFAULT,
    on_retry: Callable[[], None] | None = None,
) -> CardDraft:
    return _generate_card_via(
        word,
        level,
        prompt_template=_PROMPT_TEMPLATE_PLAIN,
        response_format=None,
        parse=_parse_plain_card,
        on_retry=on_retry,
    )
    # Same signature/return type as generate_card above- callers (backend/main.py,
    # generate_cards_batch below) only ever need to pick *which* of the two to call,
    # never handle a differently-shaped result.


def generate_card_with_events(
    word: str, level: str = JLPT_LEVEL_DEFAULT, mode: str = "structured"
) -> Iterator[dict]:
    # Runs the actual (blocking) generate_card/generate_card_plain call on a worker
    # thread via _EXECUTOR, so this generator can keep yielding progress lines to its
    # caller (backend/main.py's streaming routes, and generate_cards_batch below) while
    # the OpenRouter call is still in flight- a single `requests.post` call can't both
    # block and yield from the same call stack. signal_queue is how on_retry (see
    # _generate_card_via) tells this loop a retry started the instant it happens,
    # instead of waiting for the next heartbeat tick to notice.
    generate_fn = generate_card_plain if mode == "plain" else generate_card
    signal_queue: queue.Queue = queue.Queue()
    future = _EXECUTOR.submit(
        generate_fn, word, level=level, on_retry=lambda: signal_queue.put("retry")
    )

    start = time.monotonic()
    last_emit = start
    while not future.done():
        try:
            signal = signal_queue.get(timeout=_QUEUE_POLL_S)
        except queue.Empty:
            signal = None
        now = time.monotonic()
        if signal == "retry":
            yield {"event": "retry", "elapsed_s": round(now - start, 1)}
            last_emit = now
        elif now - last_emit >= HEARTBEAT_INTERVAL_S:
            yield {"event": "heartbeat", "elapsed_s": round(now - start, 1)}
            last_emit = now

    while True:
        # Drains any retry signal that raced with the future finishing (pushed onto
        # the queue right before attempt 2 returned), so it isn't silently dropped.
        try:
            if signal_queue.get_nowait() == "retry":
                yield {"event": "retry", "elapsed_s": round(time.monotonic() - start, 1)}
        except queue.Empty:
            break

    try:
        card = future.result()
    except LLMError as exc:
        yield {"event": "error", "detail": str(exc)}
        return
    except Exception as exc:
        yield {"event": "error", "detail": f"unexpected error generating '{word}': {exc}"}
        return
    yield {"event": "result", "card": card.model_dump()}
    # `card.model_dump()` rather than the CardDraft instance itself, so every event this
    # generator yields is already plain-JSON-serializable for callers that stream them
    # straight out as NDJSON (backend/main.py)- a caller that needs the CardDraft back
    # (generate_cards_batch below) reconstructs it via CardDraft(**event["card"]).


def generate_cards_batch(
    words: list[str], level: str = JLPT_LEVEL_DEFAULT, mode: str = "structured"
) -> Iterator[BatchCardResult | dict]:
    # A generator rather than building and returning a list- backend/main.py's
    # /generate/batch route streams one line at a time to the frontend as progress
    # happens (see _stream_batch_results there), so nothing should call generate_card
    # for word N+1 before word N's terminal result has already been handed back. Each
    # word yields zero or more progress dicts (heartbeat/retry, tagged with `word` and
    # `index` so the caller can tell which in-flight word they belong to) followed by
    # exactly one terminal BatchCardResult- generate_card_with_events already turns
    # every failure mode (including LLMError) into a terminal `error` event, which is
    # what becomes that BatchCardResult's `error` field below, so no separate
    # try/except is needed around this loop.
    for index, word in enumerate(words):
        for event in generate_card_with_events(word, level=level, mode=mode):
            if event["event"] == "result":
                yield BatchCardResult(word=word, card=CardDraft(**event["card"]))
                break
            if event["event"] == "error":
                yield BatchCardResult(word=word, error=event["detail"])
                break
            yield {**event, "word": word, "index": index}
    # Calling this with an empty `words` list yields zero times- fine, since the only
    # caller (backend/main.py) only ever iterates it in lockstep with a matching number
    # of pending slots.
