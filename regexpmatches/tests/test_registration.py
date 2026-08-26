"""Auto-registration, flags, trusted-schema, and JSON-subtype tests."""

from __future__ import annotations

import sqlite3


def test_functions_are_present_with_expected_arity(db: sqlite3.Connection) -> None:
    rows = db.execute(
        """
        SELECT name, narg, flags
        FROM pragma_function_list
        WHERE name IN ('regexpi', 'regexp_matches', 'regexpi_matches')
        ORDER BY name
        """
    ).fetchall()
    assert [(name, narg) for name, narg, _ in rows] == [
        ("regexp_matches", 2),
        ("regexpi", 2),
        ("regexpi_matches", 2),
    ]
    deterministic = 0x000000800
    innocuous = 0x000200000
    for _, _, flags in rows:
        assert flags & deterministic
        assert flags & innocuous


def test_functions_are_available_on_another_fresh_connection() -> None:
    with sqlite3.connect(":memory:") as connection:
        assert connection.execute(
            "SELECT regexp_matches('a', 'a')"
        ).fetchone()[0] == '["a"]'


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

