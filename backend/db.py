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
# Example: postgresql+psycopg://anki_tool:devpassword@localhost:5432/anki_tool
# The URL points to a database connection string (Uniform Resource Identifier). A
# database connection string contains the parameters an app needs to:
# - locate
# - authenticate with
# - establish communication with
# a database.
# Basically, it tells the app where to find the database and provides the required keys to
# "walk through the front door".
#
# From the create_engine func. description:
#   The string form of the URL is dialect[+driver]://user:password@host/dbname[?key=value..],
#   where dialect is a database name such as mysql, oracle, postgresql, etc., and driver
#   the name of a DBAPI, such as psycopg2, pyodbc, cx_oracle, etc.
#   Alternatively, the URL can be an instance of URL.

# The code below creates an instance of the Engine class, which itself references `Dialect` and
# `Pool`. To reference another class essentially means to store a memory address to where
# the 2nd object lives. An example of this occuring could be an object that has another
# as an attribute value. 
# Reminder: a database "pool connection" is just a collection of pre-opened, active DB connections
# which are created lazily as they're first needed (not necessarily all at once on app initialization).
# When an incoming request needs data, it borrows
# an idle connection from the pool rather than opening a new socket (allocating space in memory to it,
# creating it, binding it to a port...) and upon release, said connection is returned to the pool
# and not closed.
# This mechanism exists to minimise latency, handshake overhead, system calls from the DB manager SW...
engine = create_engine(DATABASE_URL)
# Note: SQLAlchemy's Engine here isn't the DBMS's own storage engine (the part of Postgres
# that parses queries and enforces atomicity, consistency, isolation and durability)- it's a
# connection/dialect layer on top of that.
# It does not handle UI administration, backup and recovery scheduling or performance reporting.
#
# engine = create_engine(DATABASE_URL) creates an Engine object, which manages a pool of database
# connections and understands how to translate Python commands into the dialect implemented
# by the DB.
#
# Moreover,
# To start sending queries over, a connection object needs to be created. Since the engine manages
# connections, it is necessary to ask the engine for a connection prior to sending statements over
# to the DB.

# sessionmaker() is a configurable factory for SQLAlchemy Session objects.
#
# A Session is not itself a database connection. It manages ORM operations,
# transactions, and the objects loaded from or persisted to the database.
# When database access is needed, the Session obtains a connection from its
# associated Engine, typically from the Engine's connection pool.
#
# A Session is usually created for a specific unit of work, such as handling
# a request or performing a particular database operation. It is not inherently
# associated with a specific user and does not normally store user credentials.
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase): # DB models inherit from the Base class.
    pass # `pass` is a placeholder in blocks where Python requires an indented statement


class Word(Base):
    __tablename__ = "words"
    __table_args__ = (Index("ix_words_kanji_level", "kanji", "level"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # id is the name, Mapped[int] functions as a type hint (indicating to both VSCode and SQLAlchemy the data type)
    # and mapped_column() configures SQLAlchemy's table/column metadata (not the live DB engine directly) to set up
    # special rules that Python types cannot express- that metadata is what's used to talk to the DB later, e.g. via
    # init_db()'s create_all().
    kanji: Mapped[str] = mapped_column(String)
    reading: Mapped[str] = mapped_column(String)
    level: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    created_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now())

    cards: Mapped[list["Card"]] = relationship(back_populates="word")
    # back_populates is used to explicitly define relationships in both models.

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
