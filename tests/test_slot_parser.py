"""Phase C gate: every row of BUILD_PLAN.md v2 Section 4's table, plus the
non-negotiable one -- the verbatim template scaffold for every slotted
column (H..R) must parse as *unfilled*, not as 6 values. Scaffold strings
are read directly from template_spec.COLUMNS, never re-typed here, so this
test can't drift out of sync with the real template.
"""

import pytest

from app.config import load_config
from app.slot_parser import MAX_SLOTS, parse_slots
from app.template_spec import COLUMNS, slotted_columns


@pytest.fixture(scope="module")
def cfg():
    return load_config()


# ============================================================================
# The non-negotiable one: untouched scaffold -> unfilled, for every slotted column
# ============================================================================


@pytest.mark.parametrize("letter", [c.letter for c in slotted_columns()])
def test_verbatim_scaffold_is_unfilled_not_six_values(cfg, letter):
    spec = COLUMNS[letter]
    result = parse_slots(spec.scaffold_raw, letter, cfg)
    assert result.is_unfilled_scaffold is True
    assert result.slots == {}


# ============================================================================
# Marker variants: "1." "1)" "(1)" "1 . " "1.ABC" all mean slot 1
# ============================================================================


@pytest.mark.parametrize(
    "text",
    [
        "1. ABC Ltd\n2. DEF Ltd",
        "1.ABC Ltd\n2.DEF Ltd",
        "1 . ABC Ltd\n2 . DEF Ltd",
        "1) ABC Ltd\n2) DEF Ltd",
        "(1) ABC Ltd\n(2) DEF Ltd",
    ],
)
def test_marker_variants_all_parse_to_same_two_slots(cfg, text):
    result = parse_slots(text, "H", cfg)
    assert result.slots == {1: "ABC Ltd", 2: "DEF Ltd"}


def test_numbering_on_one_line_beats_comma_split(cfg):
    result = parse_slots("1. ABC Ltd, 2. DEF Ltd", "H", cfg)
    assert result.slots == {1: "ABC Ltd", 2: "DEF Ltd"}


# ============================================================================
# No numbering: positional fallback
# ============================================================================


def test_no_numbering_comma_separated_positional_fallback(cfg):
    # H allows "," so unnumbered comma-joined agency names fall back positionally.
    result = parse_slots("ABC Ltd, DEF Ltd", "H", cfg)
    assert result.slots == {1: "ABC Ltd", 2: "DEF Ltd"}


def test_no_numbering_newline_separated_positional_fallback(cfg):
    result = parse_slots("ABC Ltd\nDEF Ltd", "H", cfg)
    assert result.slots == {1: "ABC Ltd", 2: "DEF Ltd"}


# ============================================================================
# Gaps are preserved, not silently renumbered
# ============================================================================


def test_gap_in_the_middle_is_preserved(cfg):
    result = parse_slots("1. Rahul\n2. Amit\n3.\n4. Suresh", "K", cfg)
    assert result.slots == {1: "Rahul", 2: "Amit", 4: "Suresh"}
    assert 3 not in result.slots


# ============================================================================
# Slots beyond the 6-slot scaffold are accepted, N grows
# ============================================================================


def test_slots_beyond_scaffold_are_accepted(cfg):
    text = "\n".join(f"{i}. Agency{i}" for i in range(1, 9))  # 8 agencies
    result = parse_slots(text, "H", cfg)
    assert len(result.slots) == 8
    assert result.slots[7] == "Agency7"
    assert result.slots[8] == "Agency8"


# ============================================================================
# Type-aware separators: PHONE allows "/", NUMBER/DATE_RANGE protect internal punctuation
# ============================================================================


def test_phone_slash_separator_gives_two_values(cfg):
    result = parse_slots("9876543210 / 9876543211", "L", cfg)
    assert result.slots == {1: "9876543210", 2: "9876543211"}


def test_number_column_digit_internal_comma_stays_one_value(cfg):
    result = parse_slots("2,500", "Q", cfg)
    assert result.slots == {1: "2,500"}


def test_number_column_two_grouped_values_on_separate_lines(cfg):
    result = parse_slots("2,500\n3,200", "Q", cfg)
    assert result.slots == {1: "2,500", 2: "3,200"}


def test_date_range_slash_never_splits(cfg):
    text = "1. From (10/08/2021) - To (14/01/2026)"
    result = parse_slots(text, "J", cfg)
    assert result.slots == {1: "From (10/08/2021) - To (14/01/2026)"}


# ============================================================================
# Normalization: NBSP, zero-width chars, \r\n, trailing whitespace
# ============================================================================


def test_nbsp_normalized_to_space(cfg):
    text = "1. Rahul Sharma\n2. Amit Kumar"
    result = parse_slots(text, "K", cfg)
    assert result.slots[1] == "Rahul Sharma"


def test_zero_width_characters_stripped(cfg):
    text = "1. Ra\u200bhul Sharma\n2. Amit Kumar"  # \u200b = zero-width space
    result = parse_slots(text, "K", cfg)
    assert result.slots[1] == "Rahul Sharma"


def test_crlf_line_endings_handled(cfg):
    result = parse_slots("1. Rahul Sharma\r\n2. Amit Kumar", "K", cfg)
    assert result.slots == {1: "Rahul Sharma", 2: "Amit Kumar"}


def test_trailing_whitespace_trimmed(cfg):
    result = parse_slots("1. Rahul Sharma   \n2. Amit Kumar   ", "K", cfg)
    assert result.slots == {1: "Rahul Sharma", 2: "Amit Kumar"}


# ============================================================================
# N/A tokens
# ============================================================================


@pytest.mark.parametrize("token", ["N/A", "NA", "Nil", "-", "Not Applicable", "n/a", "nil"])
def test_na_tokens_set_is_na_not_a_value(cfg, token):
    result = parse_slots(token, "M", cfg)
    assert result.is_na is True
    assert result.slots == {}


# ============================================================================
# Blank / empty cell
# ============================================================================


@pytest.mark.parametrize("text", ["", "   ", None])
def test_blank_or_none_is_unfilled(cfg, text):
    result = parse_slots(text, "H", cfg)
    assert result.is_unfilled_scaffold is True
    assert result.is_na is False


# ============================================================================
# Partially-filled scaffold: some slots real, rest still literal placeholder
# ============================================================================


def test_partial_fill_drops_remaining_placeholder_slots(cfg):
    text = "  1. Real Agency Co \n  2. Agency \n  3. Agency \n  4. Agency\n  5. Agency \n  6. Agency"
    result = parse_slots(text, "H", cfg)
    assert result.slots == {1: "Real Agency Co"}


def test_partial_fill_on_blank_scaffold_column(cfg):
    # I's placeholder per slot is "" (empty) -- filling only slot 2 should
    # leave just {2: ...}, not resurrect the empty slots as data.
    text = "  1. \n  2. Regular (1 year)\n  3.\n  4. \n  5.\n  6."
    result = parse_slots(text, "I", cfg)
    assert result.slots == {2: "Regular (1 year)"}


# ============================================================================
# Non-slotted columns (F, G, S): single value, no numbering expected
# ============================================================================


def test_non_slotted_column_single_value(cfg):
    result = parse_slots("Nellore Village, Chainage 12+300, Nellore City, 524001", "F", cfg)
    assert result.slots == {1: "Nellore Village, Chainage 12+300, Nellore City, 524001"}


def test_non_slotted_column_blank_is_unfilled(cfg):
    result = parse_slots("", "S", cfg)
    assert result.is_unfilled_scaffold is True


def test_non_slotted_column_ignores_numbering(cfg):
    # G (Plaza Type) is a single-value ENUM column; "1. BOT" should not be
    # sliced into slots -- there's only ever one value here.
    result = parse_slots("BOT", "G", cfg)
    assert result.slots == {1: "BOT"}


# ============================================================================
# Cap on absurd slot counts
# ============================================================================


def test_slots_beyond_max_are_dropped_and_noted(cfg):
    text = "\n".join(f"{i}. value{i}" for i in range(1, MAX_SLOTS + 10))
    result = parse_slots(text, "H", cfg)
    assert max(result.slots.keys()) <= MAX_SLOTS
    assert "truncated" in result.note


# ============================================================================
# Pure punctuation / stray separators are not values
# ============================================================================


def test_lone_slot_one_marker_is_trusted_and_stripped(cfg):
    # Only one contract, but the client numbered it anyway -- the "1. "
    # prefix must not leak into the value.
    result = parse_slots("1. Rahul Sharma", "K", cfg)
    assert result.slots == {1: "Rahul Sharma"}


def test_lone_marker_for_a_non_one_slot_is_not_trusted(cfg):
    # A single "3." with nothing else isn't corroborated by a second
    # marker, so it's treated as ordinary text, not slot 3 alone.
    result = parse_slots("3-BHK apartment near Toll Plaza", "M", cfg)
    assert result.slots == {1: "3-BHK apartment near Toll Plaza"}


def test_pure_punctuation_slot_dropped(cfg):
    result = parse_slots("1. Rahul Sharma\n2. --\n3. Amit Kumar", "K", cfg)
    assert 2 not in result.slots
    assert result.slots == {1: "Rahul Sharma", 3: "Amit Kumar"}


def test_trailing_separator_punctuation_stripped(cfg):
    result = parse_slots("1. Rahul Sharma,\n2. Amit Kumar,", "K", cfg)
    assert result.slots == {1: "Rahul Sharma", 2: "Amit Kumar"}
