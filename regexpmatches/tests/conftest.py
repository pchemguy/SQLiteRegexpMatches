"""Shared fixtures for SQL-surface tests of the amalgamated regexp extension.

The suite intentionally imports Python's standard ``sqlite3`` module and
never registers replacement Python functions.  The surrounding test command
must arrange for that module to link to the custom SQLite build.
"""

from __future__ import annotations

import json
import os
import sqlite3
import warnings
from collections.abc import Callable, Iterator

import pytest


FUNCTION_NAMES = {
    "regexp",
    "regexpi",
    "regexp_matches",
    "regexpi_matches",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add an optional diagnostic SQLite identity value."""
    parser.addoption(
        "--sqlite-source-id",
        default=os.environ.get("REGEXP_TEST_SOURCE_ID"),
        help="Optional expected sqlite_source_id(); mismatch emits a warning.",
    )


@pytest.fixture(scope="session", autouse=True)
def verify_custom_sqlite(pytestconfig: pytest.Config) -> None:
    """Verify required functions without pinning a particular SQLite version."""
    expected = pytestconfig.getoption("--sqlite-source-id")

    with sqlite3.connect(":memory:") as connection:
        version, actual = connection.execute(
            "SELECT sqlite_version(), sqlite_source_id()"
        ).fetchone()
        if expected and actual != expected:
            warnings.warn(
                f"SQLite source ID differs from diagnostic expectation: "
                f"expected {expected!r}, got {actual!r} (version {version})",
                pytest.PytestWarning,
                stacklevel=1,
            )
        assert connection.execute(
            "SELECT sqlite_compileoption_used('OMIT_JSON')"
        ).fetchone()[0] == 0
        rows = connection.execute(
            """
            SELECT name, narg
            FROM pragma_function_list
            WHERE name IN ('regexp', 'regexpi',
                           'regexp_matches', 'regexpi_matches')
            """
        ).fetchall()
        assert {(name, narg) for name, narg in rows} == {
            (name, 2) for name in FUNCTION_NAMES
        }


@pytest.fixture
def db() -> Iterator[sqlite3.Connection]:
    """Provide an isolated connection with no Python-defined SQL functions."""
    connection = sqlite3.connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def scalar(db: sqlite3.Connection) -> Callable[[str, tuple[object, ...]], object]:
    """Execute a scalar SELECT with bound parameters."""

    def execute(expression: str, parameters: tuple[object, ...] = ()) -> object:
        row = db.execute(f"SELECT {expression}", parameters).fetchone()
        assert row is not None
        return row[0]

    return execute


@pytest.fixture
def matches(
    scalar: Callable[[str, tuple[object, ...]], object],
) -> Callable[[str, str | None, object], list[str] | None]:
    """Call a match-array function and decode its JSON text result."""

    def execute(
        pattern: str | None,
        value: object,
        function: str = "regexp_matches",
    ) -> list[str] | None:
        assert function in {"regexp_matches", "regexpi_matches"}
        result = scalar(f"{function}(?, ?)", (pattern, value))
        if result is None:
            return None
        assert isinstance(result, str)
        decoded = json.loads(result)
        assert isinstance(decoded, list)
        assert all(isinstance(item, str) for item in decoded)
        return decoded

    return execute
