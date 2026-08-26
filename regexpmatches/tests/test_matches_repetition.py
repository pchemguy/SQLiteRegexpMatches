"""Greedy, non-possessive repetition tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest


@pytest.mark.parametrize(
    ("pattern", "value", "expected"),
    [
        ("a*", "aaa", ["aaa"]),
        ("a+", "aaa", ["aaa"]),
        ("a?", "a", ["a"]),
        ("a{2,4}", "aaaaa", ["aaaa"]),
        (".*a", "a 1 a 2", ["a 1 a"]),
        ("a.*b", "a1b2b", ["a1b2b"]),
        ("a.*bc", "a1bc2bc", ["a1bc2bc"]),
        ("a.*a", "aaaa", ["aaaa"]),
        ("ab*bc", "abbbc", ["abbbc"]),
        ("ab*bc", "abc", ["abc"]),
        ("(a|aa)+", "aaa", ["aaa"]),
        ("(aa|a)+", "aaa", ["aaa"]),
        ("a{2,4}a", "aaaaa", ["aaaaa"]),
        ("a{2,4}b", "aaaab", ["aaaab"]),
        ("a{2,4}b", "aaaaab", ["aaaab"]),
        ("a{2}", "aaaaa", ["aa", "aa"]),
        ("(ab?)+", "ababa", ["ababa"]),
    ],
)
def test_greedy_nonpossessive_repetition(
    matches: Callable[..., list[str]],
    pattern: str,
    value: str,
    expected: list[str],
) -> None:
    assert matches(pattern, value) == expected
