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


def test_dot_formatted_dates_are_not_shredded_into_bogus_slots(cfg):
    # Real client data: DD.MM.YYYY dates with no space between the day and
    # the delimiter ("From 30.01.2023") used to be misread as a fresh "30."
    # marker, since it's shaped identically to a legitimate zero-space
    # marker like "1.ABC". Each numbered item here is a full date range.
    text = (
        "1. From 30.01.2023 - To 23.06.2023\n"
        "  2. From 23.06.2023 - To 12.09.2023 \n"
        "  3. From 12.09.2023 to 29.01.2024"
    )
    result = parse_slots(text, "J", cfg)
    assert result.slots == {
        1: "From 30.01.2023 - To 23.06.2023",
        2: "From 23.06.2023 - To 12.09.2023",
        3: "From 12.09.2023 to 29.01.2024",
    }


def test_dot_formatted_dates_with_time_suffix_not_shredded(cfg):
    # Real client data (dates immediately preceded by the marker, no "From").
    text = (
        "1. 20.10.2020 (08:00:00 Hrs.) to 20.01.2022 (07:59:59 Hrs.)\n"
        "2. 20.01.2022 (08:00:00 Hrs.) to 22.03.2022 (07:59:59 Hrs.)"
    )
    result = parse_slots(text, "J", cfg)
    assert result.slots == {
        1: "20.10.2020 (08:00:00 Hrs.) to 20.01.2022 (07:59:59 Hrs.)",
        2: "20.01.2022 (08:00:00 Hrs.) to 22.03.2022 (07:59:59 Hrs.)",
    }


def test_decimal_number_with_two_digit_integer_part_not_shredded(cfg):
    # Real client data (DAULATPURA, column R): a decimal traffic figure
    # ("91.65") whose integer part is exactly 1-2 digits is shaped
    # identically to a zero-space marker ("91." then "65" as content) --
    # not date-shaped (no further "." or "/" inside "65"), so this needs
    # the sequence-plausibility check (_filter_implausible_jumps), not the
    # date-continuation guard, to reject the jump from "4" to "91".
    text = "1. 272.25\n2. 196.2\n3. 110.7\n4. 91.65\n5. 92.7\n6. 141.6\n7. 190.95\n8.156\n"
    result = parse_slots(text, "R", cfg)
    assert result.slots == {
        1: "272.25", 2: "196.2", 3: "110.7", 4: "91.65",
        5: "92.7", 6: "141.6", 7: "190.95", 8: "156",
    }


def test_zero_space_final_marker_with_numeric_content_still_recognized(cfg):
    # The last entry above ("8.156", no space after the delimiter) must
    # still be trusted as marker 8 -- it's a *plausible* continuation of
    # the sequence 1..7, unlike "91." after "4.", so the jump-plausibility
    # check accepts it even though its content happens to be numeric.
    result = parse_slots("1. 100\n2. 200\n3.300", "Q", cfg)
    assert result.slots == {1: "100", 2: "200", 3: "300"}


def test_house_number_with_hyphen_not_misread_as_marker(cfg):
    # Real client data (PANDILLAPALLI, column M): "# 46-738 Budhwarpet"
    # inside slot 6's own address text -- "46-" is zero-space and not
    # date-shaped, so only the jump check (46 is nowhere near the
    # established count of 6) keeps it from splitting off as a bogus slot.
    text = (
        "1. Venugopal Nagar, Ananthapur\n2. Pandillapalli Village\n"
        "3. 603, Jackson Crowne Heights\n4. Plot No.74, Orderly Bazar\n"
        "5. G-134, Preet Vihar\n6. # 46-738 Budhwarpet, Kurnool"
    )
    result = parse_slots(text, "M", cfg)
    assert result.slots[6] == "# 46-738 Budhwarpet, Kurnool"
    assert len(result.slots) == 6


def test_plot_number_with_space_not_misread_as_marker(cfg):
    # Real client data (SURJAPUR, column M): "Plot No. - 83. Azad Colony"
    # -- "83." has a real space after it, exactly like a genuine marker,
    # so no local shape check can tell them apart. Only the jump from "1"
    # straight to "83" (with "2." still to come) marks it implausible.
    text = (
        "1. Plot No. - 83. Azad Colony, Chotti Mazid, Umred Road, Nagpur\n"
        "2. 218, Swastik Chambers, Chemur, Mumbai"
    )
    result = parse_slots(text, "M", cfg)
    assert result.slots == {
        1: "Plot No. - 83. Azad Colony, Chotti Mazid, Umred Road, Nagpur",
        2: "218, Swastik Chambers, Chemur, Mumbai",
    }


def test_marker_wrapped_in_quotes_still_recognized(cfg):
    # Real client data (Bhojpuri, column M): each numbered entry pasted in
    # wrapped in literal quotes ('"1. Ranchor Infra..."'), a paste
    # artifact. The quote sits directly in front of the marker digit, so
    # without treating a quote as an acceptable lookbehind (same as
    # whitespace/comma/semicolon), the marker goes unrecognized entirely
    # and the whole cell falls back to being split line by line instead.
    text = '"1. Ranchor Infra Developers"\n"2. M/s Radheshyam Agrawal"\n"3. Coral Associates"'
    result = parse_slots(text, "H", cfg)
    assert len(result.slots) == 3
    assert result.slots[3] == "Coral Associates"


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
def test_na_tokens_on_optional_column_set_is_na_not_a_value(cfg, token):
    # S (Remarks) is the one genuinely optional column -- a deliberate
    # whole-cell "N/A" there really is a legitimate non-answer.
    result = parse_slots(token, "S", cfg)
    assert result.is_na is True
    assert result.slots == {}


@pytest.mark.parametrize("token", ["N/A", "NA", "Nil", "-", "Not Applicable", "n/a", "nil"])
def test_na_tokens_on_required_column_read_as_unfilled_not_na(cfg, token):
    # M (Address of Toll Agency) is required -- every operating toll plaza
    # has one, so a whole-cell "N/A" is treated as unfilled (-> MISSING
    # downstream), not given a free NOT_APPLICABLE pass. Confirmed against
    # real client data (KITLANA/NUNMATH: N/O/P literally "NA"/"Not
    # Available" while the plaza clearly has real agencies under contract).
    result = parse_slots(token, "M", cfg)
    assert result.is_na is False
    assert result.is_unfilled_scaffold is True
    assert result.slots == {}


# ============================================================================
# Per-slot NA/"Not Assigned": found via real client data (MAUHARI) -- a
# numbered list mixing real entries with per-slot non-answers. Unlike a
# *whole-cell* NA token (above, trusted as "this column doesn't apply"), a
# non-answer for just one slot in an otherwise-populated list must be
# dropped like an empty slot -- it does NOT become a valid value, and it
# does NOT make the whole cell is_na=True.
# ============================================================================


@pytest.mark.parametrize(
    "phrase", ["N/A", "NA", "Not Assigned", "NOT ASSIGNED", "Unassigned", "Not Available", "Nil", "-", "n.a."]
)
def test_per_slot_na_phrase_dropped_like_an_empty_slot(cfg, phrase):
    text = f"1. Rahul Sharma\n2. {phrase}\n3. Amit Kumar"
    result = parse_slots(text, "K", cfg)
    assert result.slots == {1: "Rahul Sharma", 3: "Amit Kumar"}
    assert result.is_na is False


def test_per_slot_na_does_not_set_whole_cell_is_na(cfg):
    text = "1. Rahul Sharma\n2. Not Assigned"
    result = parse_slots(text, "K", cfg)
    assert result.is_na is False
    assert result.is_unfilled_scaffold is False
    assert result.slots == {1: "Rahul Sharma"}


def test_all_slots_not_assigned_reads_as_unfilled_scaffold(cfg):
    # Every slot is a non-answer -- the cell as a whole has nothing to
    # offer, same as if it had been left as the literal placeholder.
    text = "1. Not Assigned\n2. Not Assigned\n3. Not Assigned"
    result = parse_slots(text, "K", cfg)
    assert result.is_unfilled_scaffold is True
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


def test_leading_backtick_stripped_like_a_stray_quote(cfg):
    # Real client data (tests/UPSTF Case 13.08.2026.xlsx, MORATANDI): a
    # zero-space marker left a stray backtick stuck to the name ("3.`Himanshu"),
    # which used to fail NAME validation outright over one typo'd character.
    result = parse_slots("1. Ramakrishna\n2.`Himanshu\n3. Sundar", "K", cfg)
    assert result.slots == {1: "Ramakrishna", 2: "Himanshu", 3: "Sundar"}


# ============================================================================
# Orphaned marker recovery -- found via real client data: a numbered list
# where one item's delimiter was dropped ("1 Agency" instead of "1. Agency")
# either loses that item entirely (if it's the first) or contaminates the
# previous item (if it's mid-sequence).
# ============================================================================


def test_leading_orphan_recovered_as_slot_one(cfg):
    text = "1 Agency Alpha\n2. Agency Beta\n3. Agency Gamma"
    result = parse_slots(text, "H", cfg)
    assert result.slots == {1: "Agency Alpha", 2: "Agency Beta", 3: "Agency Gamma"}


def test_embedded_orphan_recovered_from_previous_slot(cfg):
    text = "1. Rahul Sharma\n2. Amit Kumar\n3. Suresh Babu\n4. Pashupati Nath\n5 Veer Murli\n6. Nirpit Misra\n7. Surendra Kumar"
    result = parse_slots(text, "K", cfg)
    assert result.slots == {
        1: "Rahul Sharma", 2: "Amit Kumar", 3: "Suresh Babu", 4: "Pashupati Nath",
        5: "Veer Murli", 6: "Nirpit Misra", 7: "Surendra Kumar",
    }


def test_two_consecutive_embedded_orphans_both_recovered(cfg):
    # Real client data (tests/UPSTF Case 13.08.2026.xlsx, LIMDI): two names
    # in a row both drop their delimiter ("...4. Vikram . \n 5 Vikram \n 6
    # Narendra7. Yogesh..."), so slot 4's captured span swallows *both*
    # orphans. Recovery must keep re-scanning its own leftover tail, not
    # stop after the first hit -- otherwise "Narendra" stays glued onto
    # "Vikram" (failing NAME validation over the stray "6") and slot 6 is
    # never created.
    text = "1. amit\n2. RAVI\n3. Chandan\n4. Vikram . \n 5 Vikram \n 6   Narendra                7.Yogesh Singh\n8.Jitendra Jaat"
    result = parse_slots(text, "K", cfg)
    assert result.slots == {
        1: "amit", 2: "RAVI", 3: "Chandan", 4: "Vikram", 5: "Vikram",
        6: "Narendra", 7: "Yogesh Singh", 8: "Jitendra Jaat",
    }


def test_embedded_orphan_recovery_requires_a_bounding_next_slot(cfg):
    # Last slot has no "next" to bound a candidate against -- a multi-line
    # address ending in something that starts with a digit must stay whole
    # rather than risk misfiring.
    text = "1. Consultant Office, Ring Road\n2. House No 5 Main Street, Sample City, Sample District"
    result = parse_slots(text, "M", cfg)
    assert result.slots == {
        1: "Consultant Office, Ring Road",
        2: "House No 5 Main Street, Sample City, Sample District",
    }


def test_marker_after_stray_punctuation_recovered(cfg):
    # Real client data (tests/UPSTF Case 13.08.2026.xlsx, THIRPALIBADI
    # column I): a well-formed "2." marker sits right after a stray "."
    # instead of whitespace, so the primary marker regex's lookbehind
    # doesn't recognize it and the whole second value gets swallowed into
    # slot 1's text.
    text = "1.Reguler          .2.Reguler\n 3.  EQ\n 4.Regular"
    result = parse_slots(text, "I", cfg)
    assert result.slots == {1: "Reguler", 2: "Reguler", 3: "EQ", 4: "Regular"}


def test_stray_char_marker_shape_rejected_outside_the_gap_range(cfg):
    # A stray-punctuation-preceded digit+delimiter shape alone isn't rare
    # enough to trust blindly (e.g. "No.14-2" inside a room number) -- the
    # strict host_slot < candidate < next_claimed bound must still reject
    # an implausible candidate (14 doesn't fit between slot 1 and slot 2)
    # rather than fabricate a slot.
    text = "1. Consultant Office, Room No.14-2 Complex\n2. Second Office, Ring Road"
    result = parse_slots(text, "M", cfg)
    assert result.slots == {
        1: "Consultant Office, Room No.14-2 Complex",
        2: "Second Office, Ring Road",
    }


def test_embedded_orphan_not_recovered_outside_the_gap_range(cfg):
    # "5" here isn't between host_slot(2) and a next claimed slot (there is
    # none) -- must not be split out.
    text = "1. Consultant A\n2. 5 things happened here today in this office"
    result = parse_slots(text, "N", cfg)
    assert result.slots == {1: "Consultant A", 2: "5 things happened here today in this office"}


def test_embedded_orphan_recovered_on_last_slot_when_it_is_an_na_token(cfg):
    # Real client data: "7. Not Assigned\n  8 Not Assigned" -- item 8 is
    # missing its delimiter, and it's the last item so there's no next
    # marker to bound against. Unlike free-text ("5 Main Street"), a
    # recovered tail that's itself a recognized non-answer phrase is safe
    # to trust even without that bound -- real prose never ends that way.
    # Every slot here is "Not Assigned", so all 8 drop out as per-slot NA
    # rather than slot 7 ending up INVALID with a stray "8" stuck in it.
    text = (
        "1. Not Assigned\n  2. Not Assigned\n  3.Not Assigned\n  4. Not Assigned\n"
        "  5.Not Assigned\n  6.Not Assigned\n  7. Not Assigned\n  8 Not Assigned"
    )
    result = parse_slots(text, "O", cfg)
    assert result.slots == {}
    assert result.is_unfilled_scaffold is True


def test_embedded_orphan_on_last_slot_still_requires_na_token(cfg):
    # Same missing-delimiter shape, but the recovered tail is ordinary
    # prose, not a non-answer phrase -- must NOT be split out, same as the
    # bounded case above.
    text = "1. Consultant Office, Ring Road\n2. House No 5 Main Street, Sample City"
    result = parse_slots(text, "M", cfg)
    assert result.slots == {
        1: "Consultant Office, Ring Road",
        2: "House No 5 Main Street, Sample City",
    }


# ============================================================================
# Duplicate slot markers: renumber rather than silently overwrite
# ============================================================================


def test_duplicate_slot_marker_renumbered_not_discarded(cfg):
    text = "1. A\n2. B\n3. C\n4. D\n5. E\n6. Slot Six\n6. Slot Actually Seven"
    result = parse_slots(text, "H", cfg)
    assert result.slots[6] == "Slot Six"
    assert result.slots[7] == "Slot Actually Seven"
    assert len(result.slots) == 7
