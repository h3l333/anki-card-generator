import os

from ollama import Client

from backend.models import CardDraft

MODEL_NAME = "yuma/DeepSeek-R1-Distill-Qwen-Japanese:14b"

# docker-compose.yml maps this container's port 11434 to host port 11435.
client = Client(host=os.getenv("OLLAMA_HOST", "http://localhost:11435"))

_PROMPT_TEMPLATE = """\
日本語学習者(中級〜上級)向けに、次の単語についての情報をJSON形式で生成してください。

対象語: {word}

含める情報:
- expression: 単語の表記(漢字・かな)
- reading: ひらがなでの読み方
- definition_ja: 日本語のみによる単語の定義(モノリンガル)
- nuance: 使い方のニュアンス、フォーマル度、類似語との違いなどの説明
- example_sentence: ふりがな付きの自然な例文
- jlpt_level: 推定されるJLPTレベル(N5〜N1のいずれか)
"""


class LLMError(Exception):
    """Raised when Ollama is unreachable or returns a response that doesn't match the schema."""


def generate_card(word: str) -> CardDraft:
    try:
        response = client.chat(
            model=MODEL_NAME,
            messages=[
                {"role": "user", "content": _PROMPT_TEMPLATE.format(word=word)}
            ],
            format=CardDraft.model_json_schema(),
        )
        return CardDraft.model_validate_json(response.message.content)
    except Exception as exc:
        raise LLMError(f"Ollama generation failed for '{word}': {exc}") from exc
