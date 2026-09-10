# This module focuses on parsing and validating .txt files via which multiple
# cards can be requested at once.
import re # Standard Python library for working with regular expressions.

MAX_WORDS = 12

_WORD_PATTERN = re.compile(r"^[一-鿿぀-ゟ゠-ヿ]+$")


class BatchValidationError(Exception):
    """Raised when an uploaded batch file doesn't match the expected format."""

# strip() removes leading and trailing whitespaces (spaces, tabs (\t), newlines (\n)).
# splitlines() splits a multi-line string into a *list* of individual lines.
# `if line.strip()` at the end works as a "skip empty lines" guard.
def parse_and_validate(file_content: str) -> list[str]:
    words = [line.strip() for line in file_content.splitlines() if line.strip()]

    if not words:
        raise BatchValidationError("File is empty or contains no words.")

    if len(words) > MAX_WORDS:
        raise BatchValidationError(
            f"File contains {len(words)} words- the limit is {MAX_WORDS} per file."
        )

    for word in words:
        if not _WORD_PATTERN.match(word):
            raise BatchValidationError(
                f"Invalid line: '{word}'. Only kanji and kana (hiragana/katakana) "
                "are allowed, one word per line."
            )

    return words
