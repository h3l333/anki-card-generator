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


class ExportRequest(BaseModel):
    expression: str
    reading: str
    definition: str
    nuance: str
    example: str
    jlpt: str
# The request body shape for POST /export (backend/main.py)- this is what the frontend sends
# back after the user has reviewed/edited the generated card. Notice the field names don't
# match CardDraft above one-for-one: definition_ja -> definition, example_sentence -> example,
# jlpt_level -> jlpt. That's deliberate (see CLAUDE.md)- frontend/index.js is the one place
# that bridges the two shapes, reading data.definition_ja out of the /generate response into a
# form field literally named `definition`, then posting that field back under the `definition`
# key on export. Renaming a field on either this class or CardDraft without updating the other
# three places (backend/anki.py, frontend/index.js, and whichever of these two models didn't
# change) will silently break that bridge- there's no shared constant tying the names together.


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
