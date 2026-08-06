from pydantic import BaseModel, Field
# BaseModel is Pydantic's core class- subclassing it turns a plain class into a schema that
# validates and parses data automatically (e.g. rejecting a request body that's missing a
# required field, or that has the wrong type) instead of that validation being written by hand.
# Field(...) attaches metadata (like `description`) to an individual field without changing its
# type or default- see the note on CardDraft below for why that metadata matters here.


class GenerateRequest(BaseModel):
    word: str
# The request body shape for POST /generate (backend/main.py)- just the single word the user
# typed into the frontend's word input box.


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
# This is the shape the LLM is asked to return, not what the frontend sends. backend/llm.py
# calls CardDraft.model_json_schema() and passes the result to OpenRouter as the
# response_format/json_schema payload- the `description=` text on each field above isn't just
# documentation, it becomes part of the schema OpenRouter's model is instructed to fill in, so
# rewording a description here changes what the model is told to produce for that field.
# Once OpenRouter's JSON reply comes back, backend/llm.py calls
# CardDraft.model_validate_json(content) to parse and validate it into an actual instance of
# this class (raising if a field is missing or the wrong type).


class GenerateResponse(BaseModel):
    word_id: int
    duplicate: bool
    card: CardDraft
# The response body for POST /generate. `word_id` is new here- the frontend needs to carry
# it through to POST /export later, so the export route knows which word's export history
# to check (see backend/db.py's get_latest_export). `duplicate` tells the frontend whether
# `card` is a fresh LLM result or the existing pristine record already in Postgres for this
# word (see backend/main.py's generate() route and ARCHITECTURE.md)- either way `card` is
# populated, so the frontend never needs a second round-trip just to see what's on file.


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
# The request body shape for POST /export (backend/main.py)- this is what the frontend sends
# back after the user has reviewed/edited the generated card. Notice most field names don't
# match CardDraft above one-for-one: definition_ja -> definition, example_sentence -> example,
# jlpt_level -> jlpt. That's deliberate (see CLAUDE.md)- frontend/index.js is the one place
# that bridges the two shapes, reading data.definition_ja out of the /generate response into a
# form field literally named `definition`, then posting that field back under the `definition`
# key on export. synonyms/antonyms are the exception- there's no CardDraft-side qualifier to
# strip (unlike `_ja`/`_sentence`/`_level`), so both classes just use the same name and the
# bridge is a no-op for these two. Renaming a field on either this class or CardDraft without
# updating the other three places (backend/anki.py, frontend/index.js, and whichever of these
# two models didn't change) will silently break that bridge- there's no shared constant tying
# the names together.
#
# word_id is optional (default None), not required like the rest- the single-word flow's
# /generate response always includes one (GenerateResponse.word_id) and frontend/index.js
# threads it through so /export can look up export history (see the route in backend/main.py).
# The batch flow can't do the same yet- generate_cards_batch()/BatchCardResult don't persist
# anything to Postgres at all, so there's no word_id to send for a batch-generated card. When
# it's missing, /export just falls back to its old behavior (plain addNote, nothing recorded)
# rather than erroring- see backend/main.py's export() route for that branch.


class BatchGenerateRequest(BaseModel):
    file_content: str
# The request body shape for POST /generate/batch- the raw text contents of the uploaded
# .txt file, read client-side via FileReader in frontend/index.js and sent as a plain string
# rather than a file upload, so backend/batch.py never has to deal with multipart form data.


class BatchCardResult(BaseModel):
    word: str
    card: CardDraft | None = None
    error: str | None = None
# One entry per word in a batch request. `card` and `error` are mutually exclusive in
# practice- backend/llm.py::generate_cards_batch sets exactly one of the two per word
# (whichever a given word's generate_card() call actually produced), never both and never
# neither. Both default to None so a BatchCardResult can be constructed with only the field
# that applies to that word's outcome.


class BatchGenerateResponse(BaseModel):
    results: list[BatchCardResult]
# The full response body for POST /generate/batch- a list with one BatchCardResult per word in
# the uploaded file, preserving the file's original order. frontend/index.js iterates this list
# to render one carousel card per result, checking each result's `error` field to decide
# whether to show a normal editable card or an error message in its place.
