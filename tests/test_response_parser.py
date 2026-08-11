"""Phase F gate (response_parser half): per-cell parsing is a thin,
correct wrapper around slot_parser + validators, and parse_row_cells
covers exactly the 14 INPUT columns."""

import pytest

import app.validators  # noqa: F401 -- real validators, not the placeholder
from app.config import load_config
from app.excel_reader import CellRecord
from app.response_parser import build_row_index, parse_cell, parse_row_cells
from app.template_spec import SHEET_NAME, input_columns


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _cell(row, col, text, sheet=SHEET_NAME):
    from openpyxl.utils import get_column_letter

    return CellRecord(
        sheet=sheet, cell=f"{get_column_letter(col)}{row}", row=row, col=col,
        raw_value=text or None, text=text, is_merged=False, merge_anchor=None,
        number_format="General", is_bold=False, has_comment=False, comment_text=None,
        data_validation=None,
    )


# ============================================================================
# parse_cell
# ============================================================================


def test_parse_cell_with_real_values(cfg):
    cell = _cell(15, 12, "9876543210\n9876543211")
    result = parse_cell(cell, "L", cfg)
    assert result.is_na is False
    assert result.is_unfilled_scaffold is False
    assert len(result.slot_values) == 2
    assert result.slot_values[0].verdict.is_valid
    assert result.slot_values[0].verdict.normalized == "9876543210"


def test_parse_cell_none_cell_is_unfilled(cfg):
    result = parse_cell(None, "L", cfg)
    assert result.is_unfilled_scaffold is True
    assert result.slot_values == []


def test_parse_cell_untouched_scaffold(cfg):
    from app.template_spec import get_column

    scaffold = get_column("H").scaffold_raw
    cell = _cell(15, 8, scaffold)
    result = parse_cell(cell, "H", cfg)
    assert result.is_unfilled_scaffold is True
    assert result.slot_values == []


def test_parse_cell_na_token_on_required_column_is_unfilled_not_na(cfg):
    # L is required -- whole-cell "N/A" reads as unfilled (-> MISSING
    # downstream), not a free NOT_APPLICABLE pass. See slot_parser.py.
    cell = _cell(15, 12, "N/A")
    result = parse_cell(cell, "L", cfg)
    assert result.is_na is False
    assert result.is_unfilled_scaffold is True
    assert result.slot_values == []


def test_parse_cell_na_token_on_optional_column_is_na(cfg):
    cell = _cell(15, 19, "N/A")
    result = parse_cell(cell, "S", cfg)
    assert result.is_na is True
    assert result.slot_values == []


def test_parse_cell_mixed_valid_invalid(cfg):
    cell = _cell(15, 12, "9876543210\n9876\n9876543212")
    result = parse_cell(cell, "L", cfg)
    assert len(result.slot_values) == 3
    valid = [sv for sv in result.slot_values if sv.verdict.is_valid]
    assert len(valid) == 2


def test_parse_cell_non_slotted_single_value(cfg):
    cell = _cell(15, 7, "BOT")
    result = parse_cell(cell, "G", cfg)
    assert len(result.slot_values) == 1
    assert result.slot_values[0].slot == 1
    assert result.slot_values[0].verdict.is_valid


# ============================================================================
# build_row_index / parse_row_cells
# ============================================================================


def test_build_row_index_filters_by_sheet():
    cells = [_cell(15, 1, "13", sheet=SHEET_NAME), _cell(1, 1, "ignored", sheet="Instructions")]
    index = build_row_index(cells, SHEET_NAME)
    assert (15, 1) in index
    assert (1, 1) not in index


def test_parse_row_cells_covers_exactly_the_14_input_columns(cfg):
    index = build_row_index([], SHEET_NAME)
    parsed = parse_row_cells(index, None, cfg)
    expected_letters = {c.letter for c in input_columns()}
    assert set(parsed.keys()) == expected_letters
    assert expected_letters == {"F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S"}


def test_parse_row_cells_with_none_row_is_all_unfilled(cfg):
    index = build_row_index([], SHEET_NAME)
    parsed = parse_row_cells(index, None, cfg)
    assert all(p.is_unfilled_scaffold for p in parsed.values())


def test_parse_row_cells_reads_correct_columns_for_a_real_row(cfg):
    cells = [_cell(15, 12, "9876543210\n9876543211"), _cell(15, 7, "BOT")]
    index = build_row_index(cells, SHEET_NAME)
    parsed = parse_row_cells(index, 15, cfg)
    assert len(parsed["L"].slot_values) == 2
    assert len(parsed["G"].slot_values) == 1
    assert parsed["H"].is_unfilled_scaffold is True  # nothing provided for H
