"""Auto-registration, flags, trusted-schema, and JSON-subtype tests."""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest


def test_utf8_scalar_registrations(db: sqlite3.Connection) -> None:
    rows = db.execute(
        """
        SELECT name, type, narg, flags
        FROM pragma_function_list
        WHERE enc = 'utf8'
          AND name IN ('regexp', 'regexpi', 'regexp_matches', 'regexpi_matches')
        ORDER BY name
        """
    ).fetchall()
    assert [(name, kind, narg) for name, kind, narg, _ in rows] == [
        ("regexp", "s", 2),
        ("regexp_matches", "s", 2),
        ("regexpi", "s", 2),
        ("regexpi_matches", "s", 2),
    ]
    deterministic = 0x000000800
    innocuous = 0x000200000
    for _, _, _, flags in rows:
        assert flags & deterministic
        assert flags & innocuous


def test_functions_are_available_on_another_fresh_connection() -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        assert connection.execute(
            "SELECT regexp('a', 'A'), regexpi('a', 'A'), "
            "regexp_matches('a', 'A'), regexpi_matches('a', 'A')"
        ).fetchone() == (0, 1, "[]", '["A"]')


def test_matches_result_is_json_text_with_json_subtype(db: sqlite3.Connection) -> None:
    storage, kind, wrapped = db.execute(
        """
        SELECT typeof(regexp_matches('a', 'a')),
               json_type(regexp_matches('a', 'a')),
               json_array(regexp_matches('a', 'a'))
        """
    ).fetchone()
    assert storage == "text"
    assert kind == "array"
    assert wrapped == '[["a"]]'


def test_functions_are_usable_with_trusted_schema_disabled(
    db: sqlite3.Connection,
) -> None:
    db.execute("PRAGMA trusted_schema=OFF")
    db.execute(
        """
        CREATE TABLE sample(
            value TEXT,
            found TEXT GENERATED ALWAYS AS (regexp_matches('a+', value)) VIRTUAL
        )
        """
    )
    db.execute("INSERT INTO sample(value) VALUES ('caaad')")
    assert db.execute("SELECT found FROM sample").fetchone()[0] == '["aaa"]'


@pytest.mark.parametrize(
    ("function", "expected"),
    [("regexp_matches", '[["a"]]'), ("regexpi_matches", '[["Aa"]]')],
)
def test_json_subtype_with_an_expression_index(
    db: sqlite3.Connection, function: str, expected: str
) -> None:
    db.execute("PRAGMA trusted_schema=OFF")
    db.execute("CREATE TABLE sample(value TEXT)")
    db.execute("INSERT INTO sample VALUES ('xAay')")
    expression = f"{function}('a+', value)"
    db.execute(f"CREATE INDEX by_match ON sample({expression})")
    assert db.execute(
        f"SELECT json_array({expression}) FROM sample INDEXED BY by_match"
    ).fetchone() == (expected,)

