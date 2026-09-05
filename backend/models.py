from typing import Literal

from pydantic import BaseModel, Field


JlptLevel = Literal["N5", "N4", "N3", "N2", "N1"]

GenMode = Literal["structured", "plain"]


class GenerateRequest(BaseModel):
    word: str
    level: JlptLevel | None = None
    mode: GenMode = "structured"


class CardDraft(BaseModel):
    expression: str = Field(description="The word in Kanji/Kana")
    reading: str = Field(description="Reading in Hiragana")
    definition_ja: str = Field(description="Monolingual Japanese definition")
    nuance: str = Field(
        description="Usage notes, formality, and nuance versus similar words"
    )
    synonyms: str = Field(
        description='Synonyms (similar-meaning words), comma-separated; "該当なし" if none apply'
    )
    antonyms: str = Field(
        description='Antonyms (opposite-meaning words), comma-separated; "該当なし" if none apply'
    )
    example_sentence: str = Field(
        description="Natural example sentence, plain kanji/kana text (no furigana)"
    )
    jlpt_level: str = Field(description="Estimated JLPT level, N5 to N1")


class GenerateResponse(BaseModel):
    word_id: int
    duplicate: bool
    card: CardDraft


class ExportRequest(BaseModel):
    expression: str
    reading: str
    definition: str
    nuance: str
    synonyms: str
    antonyms: str
    example: str
    jlpt: str
    word_id: int | None = None
    tags: list[str] = Field(default_factory=list)


def card_draft_to_export_request(card: CardDraft, word_id: int | None = None) -> ExportRequest:
    return ExportRequest(
        expression=card.expression,
        reading=card.reading,
        definition=card.definition_ja,
        nuance=card.nuance,
        synonyms=card.synonyms,
        antonyms=card.antonyms,
        example=card.example_sentence,
        jlpt=card.jlpt_level,
        word_id=word_id,
    )


class BatchGenerateRequest(BaseModel):
    file_content: str
    level: JlptLevel | None = None
    mode: GenMode = "structured"


class BatchCardResult(BaseModel):
    word: str
    card: CardDraft | None = None
    error: str | None = None
    word_id: int | None = None
    duplicate: bool = False


Section = Literal["vocab", "grammar", "reading"]


class GrammarCard(BaseModel):
    pattern: str = Field(description="The grammar pattern itself, as written")
    connection: str = Field(description="How the pattern attaches to a verb/adjective/noun")
    meaning: str = Field(description="Monolingual Japanese explanation of what the pattern means")
    nuance: str = Field(description="Usage notes, formality, and nuance versus similar patterns")
    similar_patterns: str = Field(
        description='Grammar points with similar meaning/usage, comma-separated; "該当なし" if none apply'
    )
    example_sentence: str = Field(
        description="Natural example sentence using the pattern, plain kanji/kana text (no furigana)"
    )
    jlpt_level: str = Field(description="Estimated JLPT level of the pattern, N5 to N1")
    tags: list[str] = Field(default_factory=list)


class ReadingCard(BaseModel):
    topic: str = Field(description="The reading passage's topic/theme")
    passage: str = Field(description="The reading passage itself, plain kanji/kana text (no furigana)")
    question: str = Field(description="One comprehension question about the passage")
    answer: str = Field(description="The model answer to that question")
    vocab_notes: str = Field(description="Brief notes on any difficult vocabulary/expressions in the passage")
    jlpt_level: str = Field(description="Estimated JLPT level of the passage, N5 to N1")
    tags: list[str] = Field(default_factory=list)


class DatasetGenerateRequest(BaseModel):
    section: Section
    level: JlptLevel | None = None
    mode: GenMode = "structured"


class DatasetCardResult(BaseModel):
    item: str
    section: Section
    card: CardDraft | GrammarCard | ReadingCard | None = None
    error: str | None = None
