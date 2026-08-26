"""UTF-8 code-point matching and source-slice preservation."""

from __future__ import annotations

from collections.abc import Callable

import pytest


@pytest.mark.parametrize(
    ("pattern", "value", "expected"),
    [
        (".", "Aé€𐍈", ["A", "é", "€", "𐍈"]),
        ("é+", "xééy", ["éé"]),
        ("€|𐍈", "€x𐍈", ["€", "𐍈"]),
        (".é", "Aé𐍈é", ["Aé", "𐍈é"]),
        (r"\w+", "éabc𐍈", ["abc"]),
        ("a", "éa𐍈a", ["a", "a"]),
        ("[^é]+", "éA𐍈é", ["A𐍈"]),
    ],
)
def test_utf8_matches(
    matches: Callable[..., list[str]],
    pattern: str,
    value: str,
    expected: list[str],
) -> None:
    assert matches(pattern, value) == expected


def test_regexpi_does_not_add_unicode_case_folding(
    matches: Callable[..., list[str]],
) -> None:
    assert matches("ä", "Ää", "regexpi_matches") == ["ä"]
