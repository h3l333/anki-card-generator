import os

import requests

from backend.models import BatchCardResult, CardDraft

API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL_NAME = os.getenv("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it:free")
API_URL = "https://openrouter.ai/api/v1/chat/completions"

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


class LLMError(Exception):
    """Raised when the LLM API is unreachable, misconfigured, or returns a response that doesn't match the schema."""
    # Triple quotes in Python allow for the creation of multi-line strings and docstrings.

def generate_card(word: str) -> CardDraft:
    if not API_KEY:
        raise LLMError("OPENROUTER_API_KEY is not set - see README.md Configuration.")

    card = None
    for _attempt in range(2):
        try:
            response = requests.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": MODEL_NAME,
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
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            card = CardDraft.model_validate_json(content)
        except Exception as exc:
            raise LLMError(f"OpenRouter generation failed for '{word}': {exc}") from exc

        # Cloud models can also drift onto a different word - catch that
        # instead of silently returning a card for the wrong term.
        if word in card.expression:
            return card

    raise LLMError(
        f"Model kept substituting a different word instead of '{word}' "
        f"(got '{card.expression}') after retrying"
    )


def generate_cards_batch(words: list[str]) -> list[BatchCardResult]:
    results = []
    for word in words:
        try:
            results.append(BatchCardResult(word=word, card=generate_card(word)))
        except LLMError as exc:
            results.append(BatchCardResult(word=word, error=str(exc)))
    return results
