import os
# Same os.getenv pattern as backend/anki.py- reused here so the connection settings
# stay overridable per-machine without touching this file (see README Configuration).

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

# create_engine builds the actual connection pool SQLAlchemy talks to Postgres through.
# DeclarativeBase is the class every ORM-mapped table below inherits from- subclassing it
# is what turns a plain Python class into something SQLAlchemy knows how to translate into
# a CREATE TABLE statement and rows. Mapped/mapped_column are SQLAlchemy 2.0's typed way of
# declaring a column (Mapped[str] says "this attribute is a Python str, backed by a SQL
# column"), replacing the older untyped `Column(String)` style from SQLAlchemy 1.x.
# relationship() is separate from mapped_column()- it doesn't create a column at all, it
# tells the ORM how to load related rows (see Word.cards / Card.word below) by following
# the actual foreign key already declared via mapped_column(ForeignKey(...)).
# sessionmaker builds a factory for Session objects- a Session is the unit-of-work object
# that actually tracks pending inserts/updates and issues them via a transaction.
# func.now() (from sqlalchemy.sql) is a reference to Postgres's own NOW() SQL function-
# used below as a server_default so Postgres itself stamps created_at/exported_at, not
# Python's clock.
# select() is SQLAlchemy 2.0's query-construction entry point- used below in
# find_word_by_kanji/get_latest_export for lookups that aren't a plain primary-key get().
# BigInteger backs Export.anki_note_id below- AnkiConnect note IDs are epoch-millisecond
# timestamps (e.g. 1690000000000), which overflow a regular 32-bit Integer column.


POSTGRES_USER = os.getenv("POSTGRES_USER", "anki_tool")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "devpassword")
POSTGRES_DB = os.getenv("POSTGRES_DB", "anki_tool")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
# Deliberately reusing the same POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB names that
# docker-compose.yml already passes into the postgres container, rather than introducing
# a separate DATABASE_URL env var- one set of names to keep in sync instead of two.
# POSTGRES_HOST/POSTGRES_PORT are new (docker-compose.yml doesn't need them itself, since
# the container talks to its own Postgres process directly)- they exist here because this
# backend runs outside the container and reaches Postgres over the port docker-compose
# publishes to the host (`ports: "5432:5432"`), not through Docker's internal network.

DATABASE_URL = (
    f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)
# SQLAlchemy's connection URL format is dialect+driver://user:password@host:port/database.
# "postgresql" is the dialect (which flavor of SQL/behavior to expect); "psycopg" after the
# plus sign is the driver (which actual Python library does the talking)- this is the
# psycopg 3 package installed via requirements.txt's `psycopg[binary]` entry. Swapping to a
# different driver later (e.g. psycopg2) would only mean changing this one string.

engine = create_engine(DATABASE_URL)
# One Engine per process, created once at import time- it internally manages a pool of
# real database connections and hands them out/reclaims them as sessions need them,
# rather than this code opening a fresh TCP connection to Postgres on every query.

SessionLocal = sessionmaker(bind=engine)
# A callable factory- SessionLocal() returns a new Session bound to `engine` above. Every
# function below that talks to the database opens its own short-lived session with
# `with SessionLocal() as session:` rather than sharing one long-lived session across the
# whole app, so one function's pending changes never leak into another's.


class Base(DeclarativeBase):
    pass
# Every ORM model below inherits from this. It's what lets Base.metadata.create_all(engine)
# (see init_db() below) discover every mapped table and issue the right CREATE TABLE
# statements for it, without this file having to hand-write any SQL.


class Word(Base):
    __tablename__ = "words"
    __table_args__ = (Index("ix_words_kanji_level", "kanji", "level"),)
    # __tablename__ is the one required piece of per-class config- everything else below
    # is inferred from the type-annotated class attributes themselves. The index matches
    # find_word_by_kanji's (kanji, level) lookup below- without it, every duplicate-check
    # call (run before *every* single-word and batch-word generation) is a sequential scan,
    # and row count now grows with kanji x level combinations instead of just kanji, since
    # the same word regenerated at a different level gets its own row. Same caveat as the
    # level column itself: create_all() won't retrofit this index onto a `words` table that
    # already exists- needs a hand-run `CREATE INDEX ix_words_kanji_level ON words (kanji,
    # level);` (see the level column's ALTER TABLE note below), since there's no migration
    # tool yet (see ROADMAP.md).

    id: Mapped[int] = mapped_column(primary_key=True)
    kanji: Mapped[str] = mapped_column(String)
    reading: Mapped[str] = mapped_column(String)
    level: Mapped[str] = mapped_column(String)
    # Which JLPT level the card's language (definition_ja/nuance/example_sentence) was
    # generated for- part of find_word_by_kanji's lookup key below, so the same kanji
    # regenerated at a different level is a distinct Word row rather than reusing a card
    # written for a different audience. If a `words` table already exists from before this
    # column was added, create_all() (see init_db() below) won't retrofit it- needs either
    # `ALTER TABLE words ADD COLUMN level TEXT NOT NULL DEFAULT 'N3';` run by hand, or
    # dropping/recreating the table, since there's no migration tool yet (see ROADMAP.md).
    source: Mapped[str] = mapped_column(String)
    created_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now())
    # Matches DATABASE.md's `words` table one column at a time. server_default=func.now()
    # means Postgres itself fills this in at insert time (via its own NOW()) if the Python
    # side never sets it- so insert_word() below doesn't need to pass created_at explicitly.

    cards: Mapped[list["Card"]] = relationship(back_populates="word")
    # Not a column- this is the ORM-only, Python-side link that lets code write
    # `some_word.cards` to fetch every Card row whose word_id points at this Word, without
    # writing the join by hand. back_populates="word" is what keeps this in sync with the
    # matching `word` relationship declared on Card below (setting one updates the other's
    # in-memory view too).

    exports: Mapped[list["Export"]] = relationship(back_populates="word")
    # Same idea as cards above, pointed at the exports table instead- `some_word.exports`
    # gives every export *event* recorded for this word (see Export below for why there
    # can be more than one).


class Card(Base):
    __tablename__ = "cards"
    # Write-once by design: insert_card() below is the only place a Card row is ever
    # created, and nothing in this module ever updates its content columns afterwards.
    # That's deliberate, not an oversight- the point of persisting a card before the user
    # edits it (see insert_card()) is so this row always reflects the raw LLM output as
    # first received, even after later export cycles edit and re-edit the card on its way
    # to Anki. Those edits live only in the request payload passing through backend/main.py
    # and in Anki itself (via Export/record_export above)- never written back here.

    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"), primary_key=True)
    # DATABASE.md's `cards` table lists no id column of its own- only word_id as a FK.
    # Rather than silently inventing a surrogate id, word_id is used as cards' primary key
    # directly here, which also encodes the assumption this app currently makes: exactly
    # one card per word, never more. If that assumption changes later (e.g. regenerating a
    # card without overwriting the old one), this would need its own id column instead-
    # worth revisiting then, not guessing at now.
    definition_ja: Mapped[str] = mapped_column(Text)
    nuance: Mapped[str] = mapped_column(Text)
    synonyms: Mapped[str] = mapped_column(Text)
    antonyms: Mapped[str] = mapped_column(Text)
    # Comma-separated free text, same shape as nuance rather than a Postgres array or a
    # separate table- consistent with every other CardDraft field being a plain string,
    # and there's no current need to query "words with synonym X" individually. If a
    # cards table already exists from before this change, create_all() (see init_db()
    # below) won't retrofit these two columns onto it- that requires either an `ALTER
    # TABLE cards ADD COLUMN synonyms TEXT, ADD COLUMN antonyms TEXT;` run by hand, or
    # dropping the table and letting init_db() recreate it from scratch, since there's no
    # migration tool yet (see ROADMAP.md).
    example_sentence: Mapped[str] = mapped_column(Text)
    jlpt_level: Mapped[str] = mapped_column(String)
    exported: Mapped[bool] = mapped_column(Boolean, default=False)
    # default=False (a Python-side default, unlike created_at's server_default above) means
    # SQLAlchemy itself sends `exported=False` on insert whenever the caller doesn't set it,
    # rather than relying on Postgres to supply one.

    word: Mapped["Word"] = relationship(back_populates="cards")


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"))
    # Unlike Card.word_id above, this is *not* the primary key- word_id is deliberately
    # non-unique here, because one row is written per export *event*, not per word. Every
    # time a card is pushed to Anki (whether that's the first addNote or a later
    # updateNoteFields rewrite), a new row lands here rather than an existing one being
    # overwritten- see record_export() below. That's what makes get_latest_export() able to
    # answer "what's the current Anki note for this word" while still keeping the earlier
    # export events around as history, instead of only ever knowing the most recent state.
    anki_note_id: Mapped[int] = mapped_column(BigInteger)
    # The note ID AnkiConnect itself assigned (returned from its addNote response). This is
    # what lets a later re-export target the same Anki note via updateNoteFields instead of
    # creating a duplicate note- there's no other way to find "the note that already exists
    # for this word" without asking Anki to search for it every time.
    exported_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now())

    word: Mapped["Word"] = relationship(back_populates="exports")


def init_db() -> None:
    Base.metadata.create_all(engine)
# Base.metadata is the registry every mapped class above registered itself into just by
# inheriting from Base- create_all() walks that registry and issues CREATE TABLE ... IF NOT
# EXISTS for each one. It only ever creates missing tables; it never alters a table that
# already exists (e.g. a later added column), which is the known limitation that makes this
# fine for the very first schema but not a substitute for real migrations once the schema
# needs to change under existing data. Deliberately not called anywhere yet in this file-
# something else (a startup hook, most likely) needs to call init_db() once, later.


def insert_word(kanji: str, reading: str, source: str, level: str) -> int:
    with SessionLocal() as session:
        word = Word(kanji=kanji, reading=reading, source=source, level=level)
        session.add(word)
        session.commit()
        session.refresh(word)
        return word.id
# session.add() only stages the new row in memory- nothing reaches Postgres until commit().
# session.refresh() re-reads the row back from the database after commit, which is what
# populates word.id (and created_at) with the values Postgres actually generated- id is a
# SERIAL/identity column, so Python has no way to know its value before the insert runs.
# `with SessionLocal() as session:` closes the session automatically on the way out
# (success or exception alike), the same reason files are usually opened with `with`.


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
# Takes plain scalar fields rather than a CardDraft (backend/models.py) directly- keeps this
# module from having to import the Pydantic schema module just to read six attributes off
# it. Whatever calls insert_card() (backend/main.py) is responsible for pulling those six
# fields off its own CardDraft instance first.


def find_word_by_kanji(kanji: str, level: str) -> Word | None:
    with SessionLocal() as session:
        return session.scalar(
            select(Word).where(Word.kanji == kanji, Word.level == level)
        )
# The pre-generation duplicate check- called before spending any LLM tokens, so a word
# that's already been generated once *at this level* can short-circuit straight to the
# existing Card instead of calling OpenRouter again. session.scalar(select(...)) returns
# the first matching row or None, which is exactly the "does this exist yet" shape callers
# need. Matches on exact kanji text plus level- no fuzzy/normalized kanji matching (e.g.
# full-width vs half-width variants are different words), and a word already generated at
# one level is still treated as new the first time it's requested at a different level.
# Note the returned Word is detached once this function's `with` block exits- reading
# plain columns off it (word.id, word.kanji, ...) afterwards is fine, but touching a
# relationship (word.cards, word.exports) would raise, since lazy-loading a relationship
# needs a live session. Callers that need a word's card should use get_card() below
# instead of going through word.cards.


def get_card(word_id: int) -> Card | None:
    with SessionLocal() as session:
        return session.get(Card, word_id)
# Fetches the pristine, as-generated card for a word that's already in the database- used
# both to show the user what's already on file when a duplicate is found, and as the
# starting point for the "fetch and edit" path (the fetched fields get edited client-side,
# but this row itself is never written back to- see the module-level note on Card below).


def get_latest_export(word_id: int) -> Export | None:
    with SessionLocal() as session:
        return session.scalar(
            select(Export)
            .where(Export.word_id == word_id)
            .order_by(Export.exported_at.desc())
            .limit(1)
        )
# Answers "does an Anki note already exist for this word, and if so which one" by
# returning the most recent exports row for word_id, or None if this word has never been
# exported. The caller (backend/main.py's /export route, in a later step) uses the result
# to decide between AnkiConnect's addNote (None- nothing to rewrite yet) and
# updateNoteFields (an Export exists- reuse its anki_note_id instead of creating a
# duplicate note).


def record_export(word_id: int, anki_note_id: int) -> None:
    with SessionLocal() as session:
        session.add(Export(word_id=word_id, anki_note_id=anki_note_id))
        card = session.get(Card, word_id)
        card.exported = True
        session.commit()
# Called once per successful AnkiConnect call (addNote or updateNoteFields alike)- inserts
# the new exports row (the event this module's history is built from) and flips
# Card.exported to True in the same transaction, replacing the old standalone
# mark_exported() function so both writes happen as one commit instead of two. Card.exported
# stays as a cheap "has this word ever been exported at all" flag; get_latest_export()
# above is what answers the more specific "what's the current Anki note" question.
