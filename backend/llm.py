import os

from ollama import Client

from backend.models import CardDraft

MODEL_NAME = "yuma/DeepSeek-R1-Distill-Qwen-Japanese:14b"

# docker-compose.yml maps this container's port 11434 to host port 11435.
client = Client(host=os.getenv("OLLAMA_HOST", "http://localhost:11435"))

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
    """Raised when Ollama is unreachable or returns a response that doesn't match the schema."""


def generate_card(word: str) -> CardDraft:
    card = None
    for _attempt in range(2):
        try:
            response = client.chat(
                model=MODEL_NAME,
                messages=[
                    {"role": "user", "content": _PROMPT_TEMPLATE.format(word=word)}
                ],
                format=CardDraft.model_json_schema(),
            )
            card = CardDraft.model_validate_json(response.message.content)
        except Exception as exc:
            raise LLMError(f"Ollama generation failed for '{word}': {exc}") from exc

        # Reasoning models can drift over a long chain-of-thought and answer
        # about a different word entirely - catch that instead of silently
        # returning a card for the wrong term.
        if word in card.expression:
            return card

    raise LLMError(
        f"Model kept substituting a different word instead of '{word}' "
        f"(got '{card.expression}') after retrying"
    )
