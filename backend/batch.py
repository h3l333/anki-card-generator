import re

# re is Python's built-in regular-expression module- used here once, to build the
# pattern each word in an uploaded batch file has to match.

MAX_WORDS = 12

# Kanji, hiragana, and katakana (including the prolonged sound mark/middle dot,
# both within the katakana block)- one word per line, nothing else.
# Spelled out: 一-鿿 is the CJK Unified Ideographs block (kanji), ぀-ゟ is the
# Hiragana block, and ゠-ヿ is the Katakana block (which is why "ー", the katakana
# prolonged sound mark used in words like "ラーメン", is accepted- it lives inside
# that same Unicode range rather than needing a separate character in the pattern).
# `^...$` anchors the match to the whole line (not just part of it), and `+` requires
# at least one matching character- so an empty string alone would not satisfy this
# pattern (though parse_and_validate never actually calls this on an empty line, since
# blank lines are filtered out beforehand).
_WORD_PATTERN = re.compile(r"^[一-鿿぀-ゟ゠-ヿ]+$")
# re.compile(...) builds the pattern once, at import time, into a reusable regex
# object- since _WORD_PATTERN.match() runs once per word per request, compiling it
# ahead of time avoids re-parsing the same pattern string on every call.


class BatchValidationError(Exception):
    """Raised when an uploaded batch file doesn't match the expected format."""
    # backend/main.py's /generate/batch route catches this specifically and turns it
    # into an HTTP 400 response- a single error for the whole file, not per-line, since
    # parse_and_validate raises (and stops) on the first problem it finds rather than
    # collecting every violation before reporting back.


def parse_and_validate(file_content: str) -> list[str]: # `->` specifies expected return type.
    words = [line.strip() for line in file_content.splitlines() if line.strip()]
    # splitlines() breaks the raw uploaded text into one string per line (without the
    # trailing newline characters). The list comprehension then does two things at
    # once: line.strip() removes leading/trailing whitespace from each line, and the
    # `if line.strip()` filter drops any line that's blank (or only whitespace) so it
    # never becomes an entry in `words` at all.

    if not words:
        raise BatchValidationError("File is empty or contains no words.")
    # Catches both a truly empty file and a file that's nothing but blank lines/
    # whitespace- both end up with an empty `words` list after the step above, so
    # they're indistinguishable by this point and share the same error message.

    if len(words) > MAX_WORDS:
        raise BatchValidationError(
            f"File contains {len(words)} words- the limit is {MAX_WORDS} per file."
        )
    # This check runs before the per-word character check below on purpose- there's no
    # need to validate every individual word's characters if the file is already going
    # to be rejected for having too many of them.

    for word in words:
        if not _WORD_PATTERN.match(word):
            raise BatchValidationError(
                f"Invalid line: '{word}'. Only kanji and kana (hiragana/katakana) "
                "are allowed, one word per line."
            )
    # _WORD_PATTERN.match(word) returns a Match object (truthy) if `word` matches the
    # pattern, or None (falsy) if it doesn't- `not _WORD_PATTERN.match(word)` is true
    # exactly when the word is invalid. This loop raises (and stops) on the very first
    # bad line, so later lines in the file are never even checked once one fails.

    return words
