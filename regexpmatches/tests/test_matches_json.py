"""JSON escaping and SQLite-side JSON integration tests."""

from __future__ import annotations

import json
import sqlite3

import pytest


@pytest.mark.parametrize(
    "value",
    ['"', "\\", "\n", "\t", "\r", "\b", "\f", "\x01", "é", "𐍈"],
)
def test_every_matched_character_is_validly_escaped(
    db: sqlite3.Connection, value: str
) -> None:
    result, valid = db.execute(
        "SELECT regexp_matches('.', ?), json_valid(regexp_matches('.', ?))",
        (value, value),
    ).fetchone()
    assert valid == 1
    assert json.loads(result) == [value]


def test_multiple_escaped_members_round_trip(db: sqlite3.Connection) -> None:
    value = '"\\\n\t\x01'
    result = db.execute("SELECT regexp_matches('.', ?)", (value,)).fetchone()[0]
    assert json.loads(result) == list(value)


def test_json_each_reports_only_text_members(db: sqlite3.Connection) -> None:
    rows = db.execute(
        """
        SELECT value, type
        FROM json_each(regexp_matches('[a-z]+', 'ab  cd'))
        ORDER BY key
        """
    ).fetchall()
    assert rows == [("ab", "text"), ("cd", "text")]


def test_empty_array_is_valid_json(db: sqlite3.Connection) -> None:
    result, valid, length = db.execute(
        """
        SELECT regexp_matches('z', 'abc'),
               json_valid(regexp_matches('z', 'abc')),
               json_array_length(regexp_matches('z', 'abc'))
        """
    ).fetchone()
    assert result == "[]"
    assert valid == 1
    assert length == 0

