import os
from ollama import Client
from pydantic import BaseModel, Field

client = Client(
    host=os.getenv("OLLAMA_HOST", "http://localhost:11434")
    # If the value does not exist, it will default to port 11434
)


# Define your desired schema
class JapaneseDefinition(BaseModel):
    kanji: str = Field(description="The word in Kanji/Kana")
    reading: str = Field(description="Reading in Hiragana")
    part_of_speech: str = Field(
        description="Part of speech in Japanese (e.g., 名詞, 動詞)"
    )
    definition_ja: str = Field(description="Monolingual Japanese definition")
    example_sentence: str = Field(description="Example sentence in Japanese")


# Pass the schema directly into the `format` parameter
response = client.chat(
    model="yuma/DeepSeek-R1-Distill-Qwen-Japanese:14b",
    messages=[
        {
            "role": "user",
            "content": "「猫」という言葉の日本語の定義を生成してください。",  # Test data for proof of concept
        }
    ],
    format=JapaneseDefinition.model_json_schema(),  # Native schema enforcement
)

# Parsed directly into a structured Python object
entry = JapaneseDefinition.model_validate_json(response.message.content)
print(entry.definition_ja)
