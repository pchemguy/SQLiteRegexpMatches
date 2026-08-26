"""Global cursor, overlap exclusion, anchors, and boundaries."""

from __future__ import annotations

from collections.abc import Callable

import pytest


@pytest.mark.parametrize(
    ("pattern", "value", "expected"),
    [
        ("aa", "aaaa", ["aa", "aa"]),
        ("aba", "ababa", ["aba"]),
        ("^a", "aa", ["a"]),
        ("^.*", "abc", ["abc"]),
        ("^.*a", "a 1 a 2", ["a 1 a"]),
        ("a$", "aa", ["a"]),
        (r"\b\w+\b", "one two_three 4", ["one", "two_three", "4"]),
        (r"\bcat", "cat scatter cat", ["cat", "cat"]),
        (r"\bcat", "x catcat cat", ["cat", "cat"]),
        (r"cat\b", "cat catapult cat", ["cat", "cat"]),
        ("ab|b", "abb", ["ab", "b"]),
    ],
)
def test_successive_nonoverlapping_matches(
    matches: Callable[..., list[str]],
    pattern: str,
    value: str,
    expected: list[str],
) -> None:
    assert matches(pattern, value) == expected
