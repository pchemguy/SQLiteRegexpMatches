"""Leftmost-first and ordered-alternation selection tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest


@pytest.mark.parametrize(
    ("pattern", "value", "expected"),
    [
        ("a|aa", "aa", ["a", "a"]),
        ("aa|a", "aa", ["aa"]),
        ("a|a.*b", "a1b", ["a"]),
        ("a.*b|a", "a1b", ["a1b"]),
        ("(ab|a)b", "ab", ["ab"]),
        ("(a|ab)b", "abb", ["ab"]),
        ("a(bc|b)c", "abc", ["abc"]),
        ("a(b|bc)c", "abc", ["abc"]),
        ("z|ab", "xxab", ["ab"]),
        ("ab|b", "zab", ["ab"]),
        ("a?|aa", "aa", ["a", "a"]),
        ("aa|a?", "aa", ["aa"]),
    ],
)
def test_ordered_alternation(
    matches: Callable[..., list[str]],
    pattern: str,
    value: str,
    expected: list[str],
) -> None:
    assert matches(pattern, value) == expected


def test_higher_priority_path_may_fail_after_long_lookahead(
    matches: Callable[..., list[str]],
) -> None:
    value = "a" + "x" * 4096
    assert matches("a.*z|a", value) == ["a"]

