"""Regression coverage for the pre-existing boolean regexp SQL surface."""

from __future__ import annotations

import sqlite3

import pytest


@pytest.mark.parametrize(
    ("pattern", "value", "expected"),
    [
        ("abc", "--abc--", 1),
        ("abc", "ab", 0),
        ("^abc", "abcdef", 1),
        ("^abc", "xabc", 0),
        ("abc$", "xabc", 1),
        ("abc$", "abcx", 0),
        ("a.c", "a\nc", 1),
        ("ab*c", "ac", 1),
        ("ab+c", "ac", 0),
        ("ab?c", "ac", 1),
        ("a{2,4}", "aaa", 1),
        ("(ab|cd)e", "cde", 1),
        ("[a-c]+", "xxbcyy", 1),
        ("[^a-c]+", "abcXYZ", 1),
        (r"\d+", "x123", 1),
        (r"\D+", "123x", 1),
        (r"\w+", "---a_1", 1),
        (r"\W+", "abc---", 1),
        (r"\s+", "a\tb", 1),
        (r"\S+", " \tX", 1),
        (r"\bcat\b", "a cat!", 1),
        (r"\bcat\b", "scatter", 0),
        (r"\x41\u03b1", "Aα", 1),
    ],
)
def test_regexp_boolean_syntax(
    db: sqlite3.Connection, pattern: str, value: str, expected: int
) -> None:
    assert db.execute("SELECT regexp(?, ?)", (pattern, value)).fetchone()[0] == expected


def test_regexp_operator_reverses_arguments(db: sqlite3.Connection) -> None:
    assert db.execute("SELECT ? REGEXP ?", ("abc123", r"\d+")).fetchone()[0] == 1


def test_regexpi_is_ascii_case_insensitive(db: sqlite3.Connection) -> None:
    assert db.execute("SELECT regexpi('abc', 'xAbCy')").fetchone()[0] == 1
    assert db.execute("SELECT regexpi('ä', 'Ä')").fetchone()[0] == 0


@pytest.mark.parametrize("function", ["regexp", "regexpi"])
def test_boolean_null_propagation(db: sqlite3.Connection, function: str) -> None:
    assert db.execute(f"SELECT {function}(NULL, 'a')").fetchone()[0] is None
    assert db.execute(f"SELECT {function}('a', NULL)").fetchone()[0] is None


@pytest.mark.parametrize(
    ("pattern", "message"),
    [
        ("(", "unmatched '('") ,
        ("[a", "unclosed '['"),
        ("*a", "'*' without operand"),
        (r"\q", "unknown \\ escape"),
        ("a{3,2}", "n less than m"),
    ],
)
def test_boolean_pattern_errors(
    db: sqlite3.Connection, pattern: str, message: str
) -> None:
    with pytest.raises(sqlite3.OperationalError) as error:
        db.execute("SELECT regexp(?, 'abc')", (pattern,)).fetchone()
    assert message in str(error.value)


def test_repeated_bound_pattern_recompiles_safely(db: sqlite3.Connection) -> None:
    cursor = db.cursor()
    assert cursor.execute("SELECT regexp(?, ?)", ("a+", "aaa")).fetchone()[0] == 1
    assert cursor.execute("SELECT regexp(?, ?)", ("b+", "aaa")).fetchone()[0] == 0
