from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    word: str


class CardDraft(BaseModel):
    expression: str = Field(description="The word in Kanji/Kana")
    reading: str = Field(description="Reading in Hiragana")
    definition_ja: str = Field(description="Monolingual Japanese definition")
    nuance: str = Field(
        description="Usage notes, formality, and nuance versus similar words"
    )
    example_sentence: str = Field(
        description="Natural example sentence, plain kanji/kana text (no furigana)"
    )
    jlpt_level: str = Field(description="Estimated JLPT level, N5 to N1")


class ExportRequest(BaseModel):
    expression: str
    reading: str
    definition: str
    nuance: str
    example: str
    jlpt: str


class BatchGenerateRequest(BaseModel):
    file_content: str


class BatchCardResult(BaseModel):
    word: str
    card: CardDraft | None = None
    error: str | None = None


class BatchGenerateResponse(BaseModel):
    results: list[BatchCardResult]
