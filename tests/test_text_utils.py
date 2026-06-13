"""Tests for the em-dash replacement utility.

User-facing text must never contain an em dash. The utility replaces each one
with a colon, comma, or plain hyphen based on its context, normalising the
surrounding spacing.
"""
from __future__ import annotations

import pytest

from backend.text_utils import replace_em_dashes, to_bubbles


def test_numeric_range_becomes_hyphen() -> None:
    assert (
        replace_em_dashes("Returns were 10—12% across 2019—2024")
        == "Returns were 10-12% across 2019-2024"
    )


def test_spaced_dash_before_lowercase_becomes_comma() -> None:
    assert (
        replace_em_dashes("Rough is fine — change it anytime")
        == "Rough is fine, change it anytime"
    )


def test_dash_before_uppercase_becomes_colon() -> None:
    assert (
        replace_em_dashes("One rule — Never time the market")
        == "One rule: Never time the market"
    )


def test_unspaced_parenthetical_pair_becomes_commas() -> None:
    assert (
        replace_em_dashes("the fund—the one you mentioned—is fine")
        == "the fund, the one you mentioned, is fine"
    )


def test_dash_after_existing_punctuation_is_dropped() -> None:
    assert replace_em_dashes("Done,— extra") == "Done, extra"


def test_trailing_dash_is_removed() -> None:
    assert replace_em_dashes("I was thinking—") == "I was thinking"


def test_line_leading_dash_becomes_list_hyphen() -> None:
    assert (
        replace_em_dashes("—Buy a house\n—Retire early")
        == "- Buy a house\n- Retire early"
    )


def test_dash_at_end_of_line_keeps_newline() -> None:
    assert replace_em_dashes("first thought—\nsecond") == "first thought\nsecond"


@pytest.mark.parametrize(
    "text",
    ["", "no dashes here", "an en dash 2019–2024 stays", "hyphen-ated"],
)
def test_text_without_em_dashes_is_unchanged(text: str) -> None:
    assert replace_em_dashes(text) == text


def test_result_never_contains_em_dash() -> None:
    messy = "a—b — C, 1—2,— end—"
    assert "—" not in replace_em_dashes(messy)


# --- to_bubbles: split a reply into chat bubbles on blank lines ---


def test_single_paragraph_is_one_bubble() -> None:
    assert to_bubbles("just one thought") == ["just one thought"]


def test_blank_line_splits_into_bubbles() -> None:
    assert to_bubbles("first thought\n\nsecond thought") == [
        "first thought",
        "second thought",
    ]


def test_three_bubbles() -> None:
    assert to_bubbles("one\n\ntwo\n\nthree") == ["one", "two", "three"]


def test_extra_blank_lines_collapse_to_one_split() -> None:
    assert to_bubbles("one\n\n\n\ntwo") == ["one", "two"]


def test_whitespace_only_chunks_are_dropped() -> None:
    assert to_bubbles("one\n\n   \n\ntwo") == ["one", "two"]


def test_each_bubble_is_trimmed() -> None:
    assert to_bubbles("  hi there  ") == ["hi there"]


def test_single_newline_stays_one_bubble() -> None:
    assert to_bubbles("line one\nline two") == ["line one\nline two"]


def test_empty_or_blank_text_yields_no_bubbles() -> None:
    assert to_bubbles("") == []
    assert to_bubbles("   \n\n   ") == []


def test_em_dashes_are_stripped_per_bubble() -> None:
    assert to_bubbles("spend less—save more\n\none rule—Never time it") == [
        "spend less, save more",
        "one rule: Never time it",
    ]


def test_no_bubble_contains_an_em_dash() -> None:
    for bubble in to_bubbles("a—b\n\nc—D\n\n1—2"):
        assert "—" not in bubble
