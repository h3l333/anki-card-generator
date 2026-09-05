import os

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)
from sqlalchemy.sql import func



POSTGRES_USER = os.getenv("POSTGRES_USER", "anki_tool")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "devpassword")
POSTGRES_DB = os.getenv("POSTGRES_DB", "anki_tool")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

DATABASE_URL = (
    f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Word(Base):
    __tablename__ = "words"
    __table_args__ = (Index("ix_words_kanji_level", "kanji", "level"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kanji: Mapped[str] = mapped_column(String)
    reading: Mapped[str] = mapped_column(String)
    level: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    created_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now())

    cards: Mapped[list["Card"]] = relationship(back_populates="word")

    exports: Mapped[list["Export"]] = relationship(back_populates="word")


class Card(Base):
    __tablename__ = "cards"

    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"), primary_key=True)
    definition_ja: Mapped[str] = mapped_column(Text)
    nuance: Mapped[str] = mapped_column(Text)
    synonyms: Mapped[str] = mapped_column(Text)
    antonyms: Mapped[str] = mapped_column(Text)
    example_sentence: Mapped[str] = mapped_column(Text)
    jlpt_level: Mapped[str] = mapped_column(String)
    exported: Mapped[bool] = mapped_column(Boolean, default=False)

    word: Mapped["Word"] = relationship(back_populates="cards")


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"))
    anki_note_id: Mapped[int] = mapped_column(BigInteger)
    exported_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now())

    word: Mapped["Word"] = relationship(back_populates="exports")


def init_db() -> None:
    Base.metadata.create_all(engine)


def insert_word(kanji: str, reading: str, source: str, level: str) -> int:
    with SessionLocal() as session:
        word = Word(kanji=kanji, reading=reading, source=source, level=level)
        session.add(word)
        session.commit()
        session.refresh(word)
        return word.id


def insert_card(
    word_id: int,
    definition_ja: str,
    nuance: str,
    synonyms: str,
    antonyms: str,
    example_sentence: str,
    jlpt_level: str,
) -> None:
    with SessionLocal() as session:
        card = Card(
            word_id=word_id,
            definition_ja=definition_ja,
            nuance=nuance,
            synonyms=synonyms,
            antonyms=antonyms,
            example_sentence=example_sentence,
            jlpt_level=jlpt_level,
        )
        session.add(card)
        session.commit()


def find_word_by_kanji(kanji: str, level: str) -> Word | None:
    with SessionLocal() as session:
        return session.scalar(
            select(Word).where(Word.kanji == kanji, Word.level == level)
        )


def get_card(word_id: int) -> Card | None:
    with SessionLocal() as session:
        return session.get(Card, word_id)


def get_latest_export(word_id: int) -> Export | None:
    with SessionLocal() as session:
        return session.scalar(
            select(Export)
            .where(Export.word_id == word_id)
            .order_by(Export.exported_at.desc())
            .limit(1)
        )


def record_export(word_id: int, anki_note_id: int) -> None:
    with SessionLocal() as session:
        session.add(Export(word_id=word_id, anki_note_id=anki_note_id))
        card = session.get(Card, word_id)
        card.exported = True
        session.commit()
