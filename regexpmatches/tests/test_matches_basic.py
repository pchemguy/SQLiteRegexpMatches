"""Basic result-shape, coercion, and complete-match tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest


@pytest.mark.parametrize(
    ("pattern", "value", "expected"),
    [
        ("xyz", "abc", []),
        (r"\d+", "A12 B345", ["12", "345"]),
        ("cat", "cat", ["cat"]),
        ("cat", "catcat", ["cat", "cat"]),
        ("cat", "a cat", ["cat"]),
        ("cat", "cat!", ["cat"]),
        ("(ab)", "xxabyyab", ["ab", "ab"]),
        (".", "abc", ["a", "b", "c"]),
        (r"\D+", "12ab 34", ["ab "]),
        (r"\W+", "ab--_cd", ["--"]),
        (r"\s+", "a \t\nb", [" \t\n"]),
        (r"\S+", " a_b-9 ", ["a_b-9"]),
        ("x|^ab", "abx", ["ab", "x"]),
    ],
)
def test_basic_matches(
    matches: Callable[..., list[str]],
    pattern: str,
    value: str,
    expected: list[str],
) -> None:
    assert matches(pattern, value) == expected


def test_case_insensitive_matches_preserve_source_spelling(
    matches: Callable[..., list[str]],
) -> None:
    assert matches("ab+", "ABb ab aB", "regexpi_matches") == ["ABb", "ab", "aB"]


@pytest.mark.parametrize(
    ("pattern", "value"),
    [(None, "abc"), ("a", None)],
)
def test_null_propagation(
    matches: Callable[..., list[str] | None], pattern: str | None, value: str | None
) -> None:
    assert matches(pattern, value) is None


def test_numeric_values_follow_sqlite_text_coercion(
    matches: Callable[..., list[str]],
) -> None:
    assert matches("2", 12023) == ["2", "2"]


@pytest.mark.parametrize("function", ["regexp_matches", "regexpi_matches"])
def test_rebound_pattern_replaces_cached_compilation_safely(
    scalar: Callable[..., object], function: str
) -> None:
    assert scalar(f"{function}(?, ?)", ("a+", "aaa")) == '["aaa"]'
    assert scalar(f"{function}(?, ?)", ("b+", "aaa")) == "[]"
