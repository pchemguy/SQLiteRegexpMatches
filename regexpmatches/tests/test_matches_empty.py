"""Zero-length selection, abutting suppression, and progress tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest


@pytest.mark.parametrize(
    ("pattern", "value", "expected"),
    [
        ("", "", [""]),
        ("", "ab", ["", "", ""]),
        ("^", "abc", [""]),
        ("$", "abc", [""]),
        ("^$", "", [""]),
        ("^$", "abc", []),
        ("a*", "aaa", ["aaa"]),
        ("a*", "bbb", ["", "", "", ""]),
        ("a?", "a", ["a"]),
        ("a?", "b", ["", ""]),
        ("|a", "a", ["", ""]),
        ("a|", "a", ["a"]),
        ("(a|)", "a", ["a"]),
        ("(|a)", "a", ["", ""]),
        ("b*", "ab", ["", "b"]),
        (".*", "abc", ["abc"]),
        (".*", "", [""]),
        ("(|a)*", "aa", ["aa"]),
        ("(a|)*", "aa", ["aa"]),
        ("(|a)+", "aa", ["", "", ""]),
        ("(a?)*", "aa", ["aa"]),
        ("(a*)*", "aa", ["aa"]),
        ("$|a", "a", ["a"]),
        ("$|a", "b", [""]),
    ],
)
def test_zero_length_findall_semantics(
    matches: Callable[..., list[str]],
    pattern: str,
    value: str,
    expected: list[str],
) -> None:
    assert matches(pattern, value) == expected


def test_empty_matches_advance_by_unicode_codepoint(
    matches: Callable[..., list[str]],
) -> None:
    assert matches("", "é𐍈") == ["", "", ""]
