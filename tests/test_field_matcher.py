"""Phase 8 gate: the 3 worked examples from BUILD_PLAN.md Phase 8, plus
coverage of each strategy using hand-built FieldSpecs (no real template
needed -- match_fields only cares about the spec list's shape)."""

import pytest
from openpyxl.utils import column_index_from_string

from app.config import load_config
from app.excel_reader import CellRecord
from app.field_matcher import match_fields
from app.models import CountSource, ExpectedCount, FieldSpec, FieldType


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _spec(sheet, cell, field_name="Field") -> FieldSpec:
    return FieldSpec(
        sheet=sheet,
        cell=cell,
        field_name=field_name,
        field_type=FieldType.TEXT,
        field_type_confidence=1.0,
        expected=ExpectedCount(count=1, source=CountSource.EXPLICIT_INSTRUCTION, confidence=0.95),
        required=True,
        source="test",
        context_text="",
    )


def _resp_cell(sheet, cell, text) -> CellRecord:
    col_letters = "".join(ch for ch in cell if ch.isalpha())
    row = int("".join(ch for ch in cell if ch.isdigit()))
    return CellRecord(
        sheet=sheet,
        cell=cell,
        row=row,
        col=column_index_from_string(col_letters),
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


# ============================================================================
# The 3 Done-when examples, verbatim
# ============================================================================


def test_identical_shape_all_coordinate_matches(cfg):
    specs = [_spec("Sheet1", "A1", "Name"), _spec("Sheet1", "A2", "Phone")]
    response_cells = [_resp_cell("Sheet1", "A1", "Rahul"), _resp_cell("Sheet1", "A2", "9876543210")]

    matches, extras = match_fields(specs, response_cells, cfg)

    assert len(matches) == 2
    assert all(m.cell is not None for m in matches)
    assert all(m.strategy == "exact_coordinate" for m in matches)
    assert extras == []


def test_two_inserted_rows_recovered_via_offset(cfg):
    specs = [_spec("Sheet1", "B5", "Name"), _spec("Sheet1", "C5", "Phone"), _spec("Sheet1", "D5", "Amount")]
    # Client inserted 3 rows above the header band: the header row (labels)
    # that was at row 4 in the template is now at row 7, so the inputs
    # (directly below their headers) are now at row 8.
    response_cells = [
        _resp_cell("Sheet1", "B7", "Name"), _resp_cell("Sheet1", "C7", "Phone"), _resp_cell("Sheet1", "D7", "Amount"),
        _resp_cell("Sheet1", "B8", "Rahul Sharma"), _resp_cell("Sheet1", "C8", "9876543210"), _resp_cell("Sheet1", "D8", "25000"),
    ]

    matches, extras = match_fields(specs, response_cells, cfg)

    assert len(matches) == 3
    assert all(m.cell is not None for m in matches)
    assert all(m.strategy == "row_offset" for m in matches)
    resolved = {m.spec.field_name: m.cell.cell for m in matches}
    assert resolved == {"Name": "B8", "Phone": "C8", "Amount": "D8"}


def test_renamed_sheet_matches_via_case_normalization(cfg):
    specs = [_spec("Contact Details", "A1", "Name")]
    response_cells = [_resp_cell("contact details", "A1", "Rahul Sharma")]

    matches, extras = match_fields(specs, response_cells, cfg)

    assert len(matches) == 1
    assert matches[0].cell is not None
    assert matches[0].strategy == "sheet_name_normalized"


# ============================================================================
# Supplementary coverage
# ============================================================================


def test_completely_renamed_single_sheet_matches_via_position(cfg):
    specs = [_spec("Contact Details", "A1", "Name")]
    response_cells = [_resp_cell("Sheet1", "A1", "Rahul Sharma")]

    matches, extras = match_fields(specs, response_cells, cfg)

    assert len(matches) == 1
    assert matches[0].cell is not None
    assert matches[0].strategy == "sheet_index"


def test_missing_field_is_unmatched_not_a_crash(cfg):
    specs = [_spec("Sheet1", "A1", "Name")]
    response_cells = [_resp_cell("Sheet1", "Z99", "unrelated content")]

    matches, extras = match_fields(specs, response_cells, cfg)

    assert len(matches) == 1
    assert matches[0].cell is None
    assert matches[0].strategy == "unmatched"


def test_extra_response_cells_are_reported_and_claimed_ones_are_not(cfg):
    specs = [_spec("Sheet1", "A1", "Name")]
    response_cells = [_resp_cell("Sheet1", "A1", "Rahul"), _resp_cell("Sheet1", "B1", "unexpected extra data")]

    matches, extras = match_fields(specs, response_cells, cfg)

    assert "Sheet1!B1" in extras
    assert "Sheet1!A1" not in extras


def test_single_field_offset_guess_lacks_consensus_falls_back_to_label_match(cfg):
    # Only one field on the sheet -- a lone offset guess isn't "modal", so
    # this should resolve via plain label_match, not row_offset.
    specs = [_spec("Sheet1", "B5", "Name")]
    response_cells = [_resp_cell("Sheet1", "B9", "Name"), _resp_cell("Sheet1", "B10", "Rahul Sharma")]

    matches, extras = match_fields(specs, response_cells, cfg)

    assert len(matches) == 1
    assert matches[0].cell is not None
    assert matches[0].cell.cell == "B10"
    assert matches[0].strategy == "label_match"


def test_blank_response_cells_do_not_count_as_extras(cfg):
    specs = [_spec("Sheet1", "A1", "Name")]
    response_cells = [_resp_cell("Sheet1", "A1", "Rahul"), _resp_cell("Sheet1", "B1", "")]

    matches, extras = match_fields(specs, response_cells, cfg)

    assert extras == []


def test_multiple_sheets_resolved_independently(cfg):
    specs = [_spec("Sheet1", "A1", "Name"), _spec("sheet2", "A1", "Phone")]
    response_cells = [
        _resp_cell("Sheet1", "A1", "Rahul"),
        _resp_cell("Sheet2", "A1", "9876543210"),  # case-different rename on the second sheet only
    ]

    matches, extras = match_fields(specs, response_cells, cfg)

    by_name = {m.spec.field_name: m for m in matches}
    assert by_name["Name"].strategy == "exact_coordinate"
    assert by_name["Phone"].strategy == "sheet_name_normalized"
