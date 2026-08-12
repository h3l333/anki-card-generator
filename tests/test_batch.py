# At a high level, test_batch.py tests one function: parse_and_validate.
# parse_and_validate ensures an uploaded .txt file's contents are valid prior to any card generation.
import pytest

from backend.batch import (  # Class and function from ´batch.py´ module.
    BatchValidationError,
    parse_and_validate,
)

# backend/batch.py defines two things imported above:
#   - parse_and_validate(file_content: str) -> list[str]: takes the raw text of an uploaded
#     file, splits it into lines, strips whitespace, drops blank lines, and checks the result
#     against three rules- non-empty, no more than MAX_WORDS = 12 words, and every line
#     matches _WORD_PATTERN (kanji/hiragana/katakana only). It either returns the cleaned list
#     of words or raises BatchValidationError with a message describing which rule failed.
#   - BatchValidationError: the exception type parse_and_validate raises- these tests use
#     pytest.raises to check both that it's raised and that its message is correct.
# In backend/main.py, the /generate/batch route calls parse_and_validate(request.file_content)
# and converts any BatchValidationError straight into an HTTP 400 response (see
# test_main.py's test_generate_batch_route_maps_validation_error_to_400 for that half of the
# picture)- this file only tests parse_and_validate in isolation, not the route around it.

# pytest auto-discovers any functions named test_* in test_*.py files and runs them.
# This enables saving a developer the work of individually running each test script by just typing in the terminal
# the command `pytest`.
def test_parses_valid_words():
    assert parse_and_validate("猫\n犬\n大人") == ["猫", "犬", "大人"]
    # `assert` is a keyword- if the expression after it evaluates to `False`, the test fails and pytest reports it.

# Ensures that the function `parse_and_validate()` ignores blank lines.
def test_ignores_blank_lines():
    assert parse_and_validate("猫\n\n犬\n   \n大人") == ["猫", "犬", "大人"]

# Ensures that the function `parse_and_validate()` accepts katakana with prolonged sound marks.
def test_accepts_katakana_with_prolonged_sound_mark():
    assert parse_and_validate("ラーメン") == ["ラーメン"]
    # "ラーメン" contains "ー", the katakana prolonged sound mark- backend/batch.py's
    # _WORD_PATTERN regex explicitly includes that character in its allowed range, so this
    # guards against a future edit to that regex accidentally excluding it again.

# `pytest.raises(...)` says "the code inside this block is supposed to raise `BatchValidationError` with
# 'empty' somewhere in its message".
def test_rejects_empty_file():
    with pytest.raises(BatchValidationError, match="empty"):
        parse_and_validate("")
# The code in the prior three lines checks that `parse_and_validate("")`
# fails with a BatchValidationError mentioning "empty".
# It checks that empty input is rejected correctly.


def test_rejects_whitespace_only_file():
    with pytest.raises(BatchValidationError, match="empty"):
        parse_and_validate("   \n\n   ")
    # backend/batch.py strips each line and drops the ones that end up blank- a file that's
    # nothing but whitespace ends up with zero words after that step, so it hits the exact
    # same "File is empty or contains no words." branch as test_rejects_empty_file above.


def test_rejects_too_many_words():
    words = "\n".join(["猫"] * 13) # `(["猫"] * 13)` creates a Python list containing 13 identical elements.
    # `"\n".join(...)` merges elements in the list into a single string, placing a newline between each element.
    with pytest.raises(BatchValidationError, match="13"):
        parse_and_validate(words)
    # backend/batch.py's MAX_WORDS constant is 12- 13 words is one over that limit, so this
    # is a boundary test from the "just over" side.


def test_accepts_exactly_max_words():
    assert len(parse_and_validate("\n".join(["猫"] * 12))) == 12
    # This is the boundary test from the other side- exactly MAX_WORDS (12) words should be
    # accepted, not rejected. Testing both 12 and 13 confirms the check in backend/batch.py
    # is `> MAX_WORDS` and not `>= MAX_WORDS`.


def test_rejects_non_kanji_kana_characters():
    with pytest.raises(BatchValidationError, match="Invalid line"):
        parse_and_validate("cat\n犬")
    # "cat" is plain ASCII letters, which _WORD_PATTERN's regex doesn't match (it only allows
    # the kanji and hiragana/katakana Unicode ranges)- so parse_and_validate should stop on
    # that line specifically, even though "犬" on the next line would have been valid alone.
