"""Phase E gate: the 3 worked examples from BUILD_PLAN.md v2 Phase E,
plus coverage of each match strategy and identity-mismatch detection.
Uses the real template for the primary "identical workbook" case and
small synthetic identity-only row sets for everything else -- row_matcher
only ever reads columns A-E, so full 19-column rows aren't needed.
"""

from pathlib import Path

import pytest
from openpyxl.utils import get_column_letter

from app.excel_reader import CellRecord, read_cells
from app.row_matcher import match_rows
from app.template_spec import FIRST_DATA_ROW, LAST_DATA_ROW, SHEET_NAME

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "template" / "Format.xlsx"


def _identity_cell(sheet: str, row: int, col: int, text: str) -> CellRecord:
    return CellRecord(
        sheet=sheet,
        cell=f"{get_column_letter(col)}{row}",
        row=row,
        col=col,
        raw_value=text or None,
        text=text,
        is_merged=False,
        merge_anchor=None,
        number_format="General",
        is_bold=False,
        has_comment=False,
        comment_text=None,
        data_validation=None,
    )


def _make_rows(rows: list[tuple], start_row: int = FIRST_DATA_ROW, sheet: str = SHEET_NAME) -> list[CellRecord]:
    """rows: list of (s_no, plaza_code, plaza_name, ro, piu) tuples."""
    cells: list[CellRecord] = []
    for i, (s_no, code, name, ro, piu) in enumerate(rows):
        row_num = start_row + i
        for col, value in enumerate([s_no, code, name, ro, piu], start=1):
            cells.append(_identity_cell(sheet, row_num, col, str(value)))
    return cells


_SAMPLE = [
    (1, "111111", "ALPHA", "Delhi", "PIU-A"),
    (2, "222222", "BETA", "Delhi", "PIU-B"),
    (3, "333333", "GAMMA", "Mumbai", "PIU-C"),
    (4, "444444", "DELTA", "Mumbai", "PIU-D"),
    (5, "555555", "EPSILON", "Chennai", "PIU-E"),
]


# ============================================================================
# The 3 Done-when examples, verbatim
# ============================================================================


def test_identical_real_template_matches_115_of_115_by_s_no():
    template_cells = read_cells(str(TEMPLATE_PATH))
    response_cells = read_cells(str(TEMPLATE_PATH))  # same file = identical response

    matches = match_rows(template_cells, response_cells)

    assert len(matches) == LAST_DATA_ROW - FIRST_DATA_ROW + 1 == 115
    assert all(m.response_row is not None for m in matches)
    assert all(m.match_strategy == "s_no" for m in matches)
    assert all(m.identity_mismatches == [] for m in matches)


def test_two_rows_inserted_at_top_still_matches_all_by_s_no():
    template_cells = _make_rows(_SAMPLE, start_row=FIRST_DATA_ROW)
    # Response: same 5 plazas, but shifted down by 2 rows (as if 2 rows were
    # inserted above them) -- S.No travels with the row, so it should still
    # resolve every row correctly.
    response_cells = _make_rows(_SAMPLE, start_row=FIRST_DATA_ROW + 2)

    matches = match_rows(template_cells, response_cells)

    assert len(matches) == 5
    assert all(m.response_row is not None for m in matches)
    assert all(m.match_strategy == "s_no" for m in matches)
    resolved_rows = [m.response_row for m in matches]
    assert resolved_rows == [FIRST_DATA_ROW + 2 + i for i in range(5)]


def test_edited_plaza_name_is_reported_as_identity_mismatch():
    template_cells = _make_rows(_SAMPLE)
    edited = list(_SAMPLE)
    edited[2] = (3, "333333", "GAMMA EDITED", "Mumbai", "PIU-C")  # S.No unchanged
    response_cells = _make_rows(edited)

    matches = match_rows(template_cells, response_cells)

    gamma_match = next(m for m in matches if m.template_s_no == 3)
    assert gamma_match.match_strategy == "s_no"  # still found via S.No
    assert gamma_match.identity_mismatches
    assert "Plaza Name" in gamma_match.identity_mismatches[0]
    assert "GAMMA EDITED" in gamma_match.identity_mismatches[0]


# ============================================================================
# Strategy 2: S.No altered, Plaza Name intact
# ============================================================================


def test_cleared_s_no_falls_back_to_plaza_name_match():
    template_cells = _make_rows(_SAMPLE)
    altered = list(_SAMPLE)
    altered[1] = ("", "222222", "BETA", "Delhi", "PIU-B")  # S.No blanked
    response_cells = _make_rows(altered)

    matches = match_rows(template_cells, response_cells)

    beta_match = next(m for m in matches if m.template_plaza_name == "BETA")
    assert beta_match.response_row is not None
    assert beta_match.match_strategy == "plaza_name"


# ============================================================================
# Strategy 3: position fallback when both S.No and Plaza Name are altered
# ============================================================================


def test_position_fallback_when_both_keys_altered_but_offset_is_consistent():
    template_cells = _make_rows(_SAMPLE, start_row=FIRST_DATA_ROW)
    altered = list(_SAMPLE)
    altered[2] = ("", "333333", "GAMMA RENAMED", "Mumbai", "PIU-C")  # row index 2 -- both keys gone
    # Whole set shifted +3 rows, establishing a consistent offset from the
    # other 4 rows that DO still resolve via S.No.
    response_cells = _make_rows(altered, start_row=FIRST_DATA_ROW + 3)

    matches = match_rows(template_cells, response_cells)

    gamma_match = next(m for m in matches if m.template_plaza_name == "GAMMA")
    assert gamma_match.response_row == FIRST_DATA_ROW + 3 + 2
    assert gamma_match.match_strategy == "position"
    # Identity wasn't verified by this strategy, so the rename is caught too.
    assert gamma_match.identity_mismatches


def test_no_position_fallback_without_consistent_offset_evidence():
    # Only 1 row total, both keys altered -- nothing to establish an offset
    # from, so this should stay unmatched rather than guess.
    template_cells = _make_rows([_SAMPLE[0]])
    response_cells = _make_rows([("", "999999", "UNRECOGNIZABLE", "Delhi", "PIU-A")])

    matches = match_rows(template_cells, response_cells)

    assert matches[0].response_row is None
    assert matches[0].match_strategy == "unmatched"


# ============================================================================
# Deleted row
# ============================================================================


def test_deleted_row_is_unmatched():
    template_cells = _make_rows(_SAMPLE)
    remaining = [r for r in _SAMPLE if r[0] != 3]  # GAMMA (S.No 3) removed entirely
    response_cells = _make_rows(remaining, start_row=FIRST_DATA_ROW)  # re-packed, no gap

    matches = match_rows(template_cells, response_cells)

    gamma_match = next(m for m in matches if m.template_s_no == 3)
    assert gamma_match.response_row is None
    assert gamma_match.match_strategy == "unmatched"
    # Everything else still resolves via S.No despite the repacked rows.
    others = [m for m in matches if m.template_s_no != 3]
    assert all(m.response_row is not None for m in others)


# ============================================================================
# RO / PIU mismatches are caught too, not just Plaza Name
# ============================================================================


def test_ro_and_piu_mismatches_are_reported():
    template_cells = _make_rows(_SAMPLE)
    altered = list(_SAMPLE)
    altered[0] = (1, "111111", "ALPHA", "Mumbai", "PIU-X")  # RO and PIU both changed
    response_cells = _make_rows(altered)

    matches = match_rows(template_cells, response_cells)

    alpha_match = next(m for m in matches if m.template_s_no == 1)
    joined = " ".join(alpha_match.identity_mismatches)
    assert "RO" in joined
    assert "PIU" in joined


# ============================================================================
# Plaza Code's known unreliability: blank/dash template values never flagged
# ============================================================================


def test_blank_template_plaza_code_is_never_flagged():
    template_cells = _make_rows([(1, "", "ALPHA", "Delhi", "PIU-A")])
    response_cells = _make_rows([(1, "999999", "ALPHA", "Delhi", "PIU-A")])  # response fills it in

    matches = match_rows(template_cells, response_cells)

    assert matches[0].identity_mismatches == []


def test_dash_template_plaza_code_is_never_flagged():
    template_cells = _make_rows([(1, "-", "ALPHA", "Delhi", "PIU-A")])
    response_cells = _make_rows([(1, "999999", "ALPHA", "Delhi", "PIU-A")])

    matches = match_rows(template_cells, response_cells)

    assert matches[0].identity_mismatches == []
