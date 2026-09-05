import os

from collections.abc import Callable, Iterator

import queue
import re

import time
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

import requests

from pydantic import BaseModel

from backend.datasets import REQUIRED_ITEM_KEY
from backend.models import (
    BatchCardResult,
    CardDraft,
    DatasetCardResult,
    GrammarCard,
    ReadingCard,
    Section,
)

T = TypeVar("T", bound=BaseModel)

API_KEY = os.getenv("OPENROUTER_API_KEY")

DEFAULT_MODELS = "google/gemma-4-26b-a4b-it:free,openai/gpt-oss-20b:free,nvidia/nemotron-3-super-120b-a12b:free"

MODEL_NAMES = [
    m.strip() for m in os.getenv("OPENROUTER_MODELS", DEFAULT_MODELS).split(",") if m.strip()
]

API_URL = "https://openrouter.ai/api/v1/chat/completions"

_EXECUTOR = ThreadPoolExecutor(max_workers=4)

HEARTBEAT_INTERVAL_S = 2.5

_QUEUE_POLL_S = 0.2

JLPT_LEVEL_DEFAULT = os.getenv("JLPT_LEVEL_DEFAULT", "N3")

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


def _parse_plain_fields(text: str, labels: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-*•\t ")
        if not line or (":" not in line and "：" not in line):
            continue
        label, value = re.split(r"[:：]", line, maxsplit=1)
        label = label.strip().upper()
        if label in labels:
            fields[label.lower()] = value.strip()

    missing = [label for label in labels if label.lower() not in fields]
    if missing:
        raise ValueError(
            f"plain-text response missing labeled field(s): {', '.join(missing)}"
        )
    return fields


def _parse_plain_card(text: str) -> CardDraft:
    return CardDraft(**_parse_plain_fields(text, _PLAIN_LABELS))


class LLMError(Exception):
    """Raised when the LLM API is unreachable, misconfigured, or returns a response that doesn't match the schema."""

def _generate_card_via(
    item_label: str,
    *,
    prompt: str,
    response_format: dict | None,
    parse: Callable[[str], T],
    verify: Callable[[T], bool] = lambda _card: True,
    verify_fail_message: Callable[[T], str] | None = None,
    on_retry: Callable[[], None] | None = None,
) -> T:
    if not API_KEY:
        raise LLMError("OPENROUTER_API_KEY is not set- see README.md Configuration.")

    card: T | None = None
    for attempt_index in range(2):
        try:
            payload = {
                "models": MODEL_NAMES,
                "messages": [{"role": "user", "content": prompt}],
            }
            if response_format is not None:
                payload["response_format"] = response_format
            response = requests.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=180,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            card = parse(content)
        except Exception as exc:
            raise LLMError(f"OpenRouter generation failed for '{item_label}': {exc}") from exc

        if verify(card):
            return card

        if attempt_index == 0 and on_retry is not None:
            on_retry()

    if verify_fail_message is not None:
        raise LLMError(verify_fail_message(card))
    raise LLMError(f"Model output failed verification for '{item_label}' after retrying")


def _word_verify_fail_message(word: str) -> Callable[[CardDraft], str]:
    return lambda card: (
        f"Model kept substituting a different word instead of '{word}' "
        f"(got '{card.expression}') after retrying"
    )


def generate_card(
    word: str,
    level: str = JLPT_LEVEL_DEFAULT,
    on_retry: Callable[[], None] | None = None,
) -> CardDraft:
    return _generate_card_via(
        word,
        prompt=_PROMPT_TEMPLATE.format(word=word, level=level),
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "CardDraft",
                "strict": True,
                "schema": CardDraft.model_json_schema(),
            },
        },
        parse=CardDraft.model_validate_json,
        verify=lambda card: word in card.expression,
        verify_fail_message=_word_verify_fail_message(word),
        on_retry=on_retry,
    )


def generate_card_plain(
    word: str,
    level: str = JLPT_LEVEL_DEFAULT,
    on_retry: Callable[[], None] | None = None,
) -> CardDraft:
    return _generate_card_via(
        word,
        prompt=_PROMPT_TEMPLATE_PLAIN.format(word=word, level=level),
        response_format=None,
        parse=_parse_plain_card,
        verify=lambda card: word in card.expression,
        verify_fail_message=_word_verify_fail_message(word),
        on_retry=on_retry,
    )


def generate_card_with_events(
    arg,
    level: str = JLPT_LEVEL_DEFAULT,
    mode: str = "structured",
    generate_fn: Callable[..., BaseModel] | None = None,
) -> Iterator[dict]:
    if generate_fn is None:
        generate_fn = generate_card_plain if mode == "plain" else generate_card
    signal_queue: queue.Queue = queue.Queue()
    future = _EXECUTOR.submit(
        generate_fn, arg, level=level, on_retry=lambda: signal_queue.put("retry")
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
        yield {"event": "error", "detail": f"unexpected error generating '{arg}': {exc}"}
        return
    yield {"event": "result", "card": card.model_dump()}


def generate_cards_batch(
    words: list[str], level: str = JLPT_LEVEL_DEFAULT, mode: str = "structured"
) -> Iterator[BatchCardResult | dict]:
    for index, word in enumerate(words):
        for event in generate_card_with_events(word, level=level, mode=mode):
            if event["event"] == "result":
                yield BatchCardResult(word=word, card=CardDraft(**event["card"]))
                break
            if event["event"] == "error":
                yield BatchCardResult(word=word, error=event["detail"])
                break
            yield {**event, "word": word, "index": index}




def _schema_without_tags(model_cls: type[BaseModel]) -> dict:
    schema = model_cls.model_json_schema()
    schema["properties"].pop("tags", None)
    if "required" in schema:
        schema["required"] = [name for name in schema["required"] if name != "tags"]
    return schema


_GRAMMAR_PROMPT_TEMPLATE = """\
対象の文法項目: 「{pattern}」
想定読者のレベル: JLPT {level}
{seed_context}
あなたは日本語学習者向けの文法カードを作成します。
必ず「{pattern}」についてのみ回答してください。他の文法項目に置き換えないでください。
meaning、nuance、example_sentenceは、JLPT {level}の学習者が理解できる語彙と文法だけを使って書いてください。

次の情報をJSON形式で生成してください:
- pattern: 「{pattern}」の表記
- connection: 「{pattern}」の接続方法(例: 動詞辞書形+〜など)
- meaning: 「{pattern}」の日本語のみによる意味の説明(モノリンガル)。JLPT {level}レベル向け。
- nuance: 「{pattern}」の使い方のニュアンス、フォーマル度、類似の文法項目との違いなど。JLPT {level}レベル向け。
- similar_patterns: 「{pattern}」と意味・用法が似ている文法項目。読点で区切って複数挙げてください。該当するものがなければ「該当なし」と書いてください。
- example_sentence: 「{pattern}」を使った自然な例文。JLPT {level}レベルの学習者向けに、ふりがなは付けず、漢字とかなのみのプレーンテキストで書いてください。
- jlpt_level: 「{pattern}」の推定されるJLPTレベル(N5〜N1のいずれか)。

繰り返しますが、対象の文法項目は「{pattern}」です。
"""

_GRAMMAR_PROMPT_TEMPLATE_PLAIN = """\
対象の文法項目: 「{pattern}」
想定読者のレベル: JLPT {level}
{seed_context}
あなたは日本語学習者向けの文法カードを作成します。
必ず「{pattern}」についてのみ回答してください。他の文法項目に置き換えないでください。
meaning、nuance、example_sentenceは、JLPT {level}の学習者が理解できる語彙と文法だけを使って書いてください。

次の7項目を、必ず英大文字のラベルで始まる1行ずつの形式で出力してください。
ラベルの直後にコロン(:)、半角スペース、続けて値のみを同じ行に書いてください。
マークダウンの見出しや箇条書き記号(-、*、#など)、番号付けは使わないでください。
各項目の値は改行を含めず1行に収めてください。ラベルと値の7行以外は一切出力しないでください(前置きや説明文も禁止)。

PATTERN: 「{pattern}」の表記
CONNECTION: 「{pattern}」の接続方法
MEANING: 「{pattern}」の日本語のみによる意味の説明(モノリンガル)。JLPT {level}レベル向け。
NUANCE: 「{pattern}」の使い方のニュアンス、フォーマル度、類似の文法項目との違いなど。JLPT {level}レベル向け。
SIMILAR_PATTERNS: 「{pattern}」と意味・用法が似ている文法項目。読点で区切って複数挙げる。該当するものがなければ「該当なし」。
EXAMPLE_SENTENCE: 「{pattern}」を使った自然な例文。ふりがなは付けず、漢字とかなのみのプレーンテキスト。
JLPT_LEVEL: 「{pattern}」の推定JLPTレベル(N5〜N1のいずれか一つ)。

繰り返しますが、対象の文法項目は「{pattern}」です。出力は上記の各行のみで、それ以外の文章は一切含めないでください。
"""

_GRAMMAR_PLAIN_LABELS = [
    "PATTERN",
    "CONNECTION",
    "MEANING",
    "NUANCE",
    "SIMILAR_PATTERNS",
    "EXAMPLE_SENTENCE",
    "JLPT_LEVEL",
]


def _grammar_seed_context(item: dict) -> str:
    hints = []
    if item.get("connection_hint"):
        hints.append(f"参考(接続): {item['connection_hint']}")
    if item.get("meaning_hint"):
        hints.append(f"参考(意味): {item['meaning_hint']}")
    return ("\n".join(hints) + "\n") if hints else ""


def _parse_plain_grammar_card(text: str) -> GrammarCard:
    return GrammarCard(**_parse_plain_fields(text, _GRAMMAR_PLAIN_LABELS))


def _pattern_verify_fail_message(pattern: str) -> Callable[[GrammarCard], str]:
    return lambda card: (
        f"Model kept substituting a different grammar pattern instead of '{pattern}' "
        f"(got '{card.pattern}') after retrying"
    )


def generate_grammar_card(
    item: dict,
    level: str = JLPT_LEVEL_DEFAULT,
    on_retry: Callable[[], None] | None = None,
) -> GrammarCard:
    pattern = item["pattern"]
    return _generate_card_via(
        pattern,
        prompt=_GRAMMAR_PROMPT_TEMPLATE.format(
            pattern=pattern, level=level, seed_context=_grammar_seed_context(item)
        ),
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "GrammarCard",
                "strict": True,
                "schema": _schema_without_tags(GrammarCard),
            },
        },
        parse=GrammarCard.model_validate_json,
        verify=lambda card: pattern in card.pattern,
        verify_fail_message=_pattern_verify_fail_message(pattern),
        on_retry=on_retry,
    )


def generate_grammar_card_plain(
    item: dict,
    level: str = JLPT_LEVEL_DEFAULT,
    on_retry: Callable[[], None] | None = None,
) -> GrammarCard:
    pattern = item["pattern"]
    return _generate_card_via(
        pattern,
        prompt=_GRAMMAR_PROMPT_TEMPLATE_PLAIN.format(
            pattern=pattern, level=level, seed_context=_grammar_seed_context(item)
        ),
        response_format=None,
        parse=_parse_plain_grammar_card,
        verify=lambda card: pattern in card.pattern,
        verify_fail_message=_pattern_verify_fail_message(pattern),
        on_retry=on_retry,
    )


_READING_PROMPT_TEMPLATE = """\
対象のトピック: 「{topic}」
想定読者のレベル: JLPT {level}

あなたは日本語学習者向けの読解問題を作成します。
{passage_instruction}
question、answerは、JLPT {level}の学習者が理解できる語彙と文法だけを使って書いてください。

次の情報をJSON形式で生成してください:
- topic: 「{topic}」
- passage: 読解文章そのもの(ふりがなは付けず、漢字とかなのみのプレーンテキスト)
- question: 文章の内容に関する読解問題を1つ
- answer: 上記の問題に対する模範解答
- vocab_notes: 文章中の難しい語彙や表現についての簡単な説明
- jlpt_level: この文章の推定JLPTレベル(N5〜N1のいずれか)

繰り返しますが、対象のトピックは「{topic}」です。
"""

_READING_PROMPT_TEMPLATE_PLAIN = """\
対象のトピック: 「{topic}」
想定読者のレベル: JLPT {level}

あなたは日本語学習者向けの読解問題を作成します。
{passage_instruction}
question、answerは、JLPT {level}の学習者が理解できる語彙と文法だけを使って書いてください。

次の6項目を、必ず英大文字のラベルで始まる1行ずつの形式で出力してください。
ラベルの直後にコロン(:)、半角スペース、続けて値のみを同じ行に書いてください。
マークダウンの見出しや箇条書き記号(-、*、#など)、番号付けは使わないでください。
各項目の値は改行を含めず1行に収めてください。ラベルと値の6行以外は一切出力しないでください(前置きや説明文も禁止)。

TOPIC: 「{topic}」
PASSAGE: 読解文章そのもの(ふりがなは付けず、漢字とかなのみのプレーンテキスト)
QUESTION: 文章の内容に関する読解問題を1つ
ANSWER: 上記の問題に対する模範解答
VOCAB_NOTES: 文章中の難しい語彙や表現についての簡単な説明
JLPT_LEVEL: この文章の推定JLPTレベル(N5〜N1のいずれか一つ)

繰り返しますが、対象のトピックは「{topic}」です。出力は上記の各行のみで、それ以外の文章は一切含めないでください。
"""

_READING_PLAIN_LABELS = [
    "TOPIC",
    "PASSAGE",
    "QUESTION",
    "ANSWER",
    "VOCAB_NOTES",
    "JLPT_LEVEL",
]


def _reading_passage_instruction(item: dict, level: str) -> str:
    passage_text = item.get("passage_text")
    if passage_text:
        return (
            "以下の文章をそのままpassageとして使い、それに基づいて読解問題を作成してください:\n"
            f"{passage_text}"
        )
    return (
        f"上記のトピックについて、JLPT {level}レベル向けの新しい読解文章を作成し、"
        "それに基づいて読解問題を作成してください。"
    )


def _parse_plain_reading_card(text: str) -> ReadingCard:
    return ReadingCard(**_parse_plain_fields(text, _READING_PLAIN_LABELS))


def _topic_verify_fail_message(topic: str) -> Callable[[ReadingCard], str]:
    return lambda card: (
        f"Model kept substituting a different topic instead of '{topic}' "
        f"(got '{card.topic}') after retrying"
    )


def generate_reading_card(
    item: dict,
    level: str = JLPT_LEVEL_DEFAULT,
    on_retry: Callable[[], None] | None = None,
) -> ReadingCard:
    topic = item["topic"]
    return _generate_card_via(
        topic,
        prompt=_READING_PROMPT_TEMPLATE.format(
            topic=topic, level=level, passage_instruction=_reading_passage_instruction(item, level)
        ),
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "ReadingCard",
                "strict": True,
                "schema": _schema_without_tags(ReadingCard),
            },
        },
        parse=ReadingCard.model_validate_json,
        verify=lambda card: topic in card.topic,
        verify_fail_message=_topic_verify_fail_message(topic),
        on_retry=on_retry,
    )


def generate_reading_card_plain(
    item: dict,
    level: str = JLPT_LEVEL_DEFAULT,
    on_retry: Callable[[], None] | None = None,
) -> ReadingCard:
    topic = item["topic"]
    return _generate_card_via(
        topic,
        prompt=_READING_PROMPT_TEMPLATE_PLAIN.format(
            topic=topic, level=level, passage_instruction=_reading_passage_instruction(item, level)
        ),
        response_format=None,
        parse=_parse_plain_reading_card,
        verify=lambda card: topic in card.topic,
        verify_fail_message=_topic_verify_fail_message(topic),
        on_retry=on_retry,
    )


_DATASET_GENERATORS: dict[tuple[Section, str], Callable[..., BaseModel]] = {
    ("vocab", "structured"): lambda item, level=JLPT_LEVEL_DEFAULT, on_retry=None: generate_card(
        item["word"], level=level, on_retry=on_retry
    ),
    ("vocab", "plain"): lambda item, level=JLPT_LEVEL_DEFAULT, on_retry=None: generate_card_plain(
        item["word"], level=level, on_retry=on_retry
    ),
    ("grammar", "structured"): lambda item, level=JLPT_LEVEL_DEFAULT, on_retry=None: generate_grammar_card(
        item, level=level, on_retry=on_retry
    ),
    ("grammar", "plain"): lambda item, level=JLPT_LEVEL_DEFAULT, on_retry=None: generate_grammar_card_plain(
        item, level=level, on_retry=on_retry
    ),
    ("reading", "structured"): lambda item, level=JLPT_LEVEL_DEFAULT, on_retry=None: generate_reading_card(
        item, level=level, on_retry=on_retry
    ),
    ("reading", "plain"): lambda item, level=JLPT_LEVEL_DEFAULT, on_retry=None: generate_reading_card_plain(
        item, level=level, on_retry=on_retry
    ),
}

_CARD_CLS: dict[Section, type[BaseModel]] = {
    "vocab": CardDraft,
    "grammar": GrammarCard,
    "reading": ReadingCard,
}


def generate_dataset_batch(
    items: list[dict],
    section: Section,
    level: str = JLPT_LEVEL_DEFAULT,
    mode: str = "structured",
) -> Iterator[DatasetCardResult | dict]:
    generate_fn = _DATASET_GENERATORS[(section, mode)]
    item_key = REQUIRED_ITEM_KEY[section]
    for index, item in enumerate(items):
        item_label = item[item_key]
        for event in generate_card_with_events(
            item, level=level, mode=mode, generate_fn=generate_fn
        ):
            if event["event"] == "result":
                card = _CARD_CLS[section](**event["card"])
                yield DatasetCardResult(item=item_label, section=section, card=card)
                break
            if event["event"] == "error":
                yield DatasetCardResult(item=item_label, section=section, error=event["detail"])
                break
            yield {**event, "item": item_label, "index": index}
