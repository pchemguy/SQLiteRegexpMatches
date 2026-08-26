"""NULL, conversion, compiler-error, and connection-limit tests."""

from __future__ import annotations

import sqlite3

import pytest


@pytest.mark.parametrize("function", ["regexp_matches", "regexpi_matches"])
@pytest.mark.parametrize(
    ("pattern", "message"),
    [
        ("(", "unmatched '('") ,
        ("[a", "unclosed '['"),
        ("*a", "'*' without operand"),
        (r"\q", "unknown \\ escape"),
        ("a{3,2}", "n less than m"),
        ("[[:alpha:]]", "POSIX character classes not supported"),
    ],
)
def test_pattern_errors_match_existing_compiler(
    db: sqlite3.Connection, function: str, pattern: str, message: str
) -> None:
    with pytest.raises(sqlite3.OperationalError) as error:
        db.execute(f"SELECT {function}(?, 'abc')", (pattern,)).fetchone()
    assert message in str(error.value)


@pytest.mark.parametrize("function", ["regexp_matches", "regexpi_matches"])
def test_pattern_length_obeys_connection_limit(
    db: sqlite3.Connection, function: str
) -> None:
    category = sqlite3.SQLITE_LIMIT_LIKE_PATTERN_LENGTH
    previous = db.setlimit(category, 4)
    try:
        with pytest.raises(sqlite3.OperationalError, match="REGEXP pattern too big"):
            db.execute(f"SELECT {function}(?, 'aaaaa')", ("aaaaa",)).fetchone()
        assert db.execute(f"SELECT {function}(?, 'aaaa')", ("aaaa",)).fetchone()[0]
    finally:
        db.setlimit(category, previous)


def test_error_does_not_poison_later_call(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.OperationalError):
        db.execute("SELECT regexp_matches('[', 'x')").fetchone()
    assert db.execute("SELECT regexp_matches('x', 'x')").fetchone()[0] == '["x"]'

