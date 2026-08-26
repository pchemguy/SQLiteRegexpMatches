"""Public-SQL adversarial tests for non-backtracking behavior."""

from __future__ import annotations

import json
import sqlite3
import time

import pytest


def timed_matches(
    db: sqlite3.Connection, pattern: str, value: str
) -> tuple[list[str], float]:
    """Execute one public SQL call and return its decoded result and duration."""
    started = time.perf_counter()
    result = db.execute("SELECT regexp_matches(?, ?)", (pattern, value)).fetchone()[0]
    elapsed = time.perf_counter() - started
    return json.loads(result), elapsed


@pytest.mark.complexity
@pytest.mark.parametrize(
    "pattern",
    [
        "(a+)+b",
        "(a|aa)*b",
        "(a?|aa)+b",
    ],
)
def test_ambiguous_failure_has_no_catastrophic_backtracking(
    db: sqlite3.Connection, pattern: str
) -> None:
    _, short = timed_matches(db, pattern, "a" * 512)
    result, long = timed_matches(db, pattern, "a" * 4096)
    assert result == []
    assert long < 5.0
    assert long < max(0.05, short) * 40


@pytest.mark.complexity
def test_many_bounded_optional_paths_remain_bounded(db: sqlite3.Connection) -> None:
    pattern = "(a?){24}a{24}"
    result, elapsed = timed_matches(db, pattern, "a" * 24)
    assert result == ["a" * 24]
    assert elapsed < 5.0


@pytest.mark.complexity
def test_documented_global_restart_fallback_case(db: sqlite3.Connection) -> None:
    value = "a" * 1200
    result, elapsed = timed_matches(db, "a.*z|a", value)
    assert result == ["a"] * len(value)
    assert elapsed < 10.0

