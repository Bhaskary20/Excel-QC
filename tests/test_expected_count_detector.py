"""Phase 6 gate: the 5 worked examples from BUILD_PLAN.md Phase 6, plus
coverage of each of the 6 detection strategies and the never-guess cap."""

import pytest
from openpyxl.utils import get_column_letter

from app.config import load_config
from app.excel_reader import CellRecord
from app.expected_count_detector import detect_expected_count
from app.models import CountSource


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _mk_cell(row, col, text, sheet="Sheet1", data_validation=None) -> CellRecord:
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
        data_validation=data_validation,
    )


# ============================================================================
# The 5 Done-when examples, verbatim
# ============================================================================


def test_explicit_instruction_provide_n(cfg):
    result = detect_expected_count("Provide 10 contact numbers", [], [], None, cfg)
    assert result.count == 10
    assert result.source == CountSource.EXPLICIT_INSTRUCTION
    assert result.confidence >= 0.95


def test_numbered_range_sno(cfg):
    result = detect_expected_count("S.No. 1-10", [], [], None, cfg)
    assert result.count == 10
    assert result.source == CountSource.NUMBERED_RANGE


def test_enumerated_labels_person_1_to_10(cfg):
    sheet_cells = [_mk_cell(row=r, col=1, text=f"Person {r}") for r in range(1, 11)]
    result = detect_expected_count("Affected Persons", [], sheet_cells, sheet_cells[0], cfg)
    assert result.count == 10
    assert result.source == CountSource.ENUMERATED_LABELS


def test_no_signal_returns_unknown_at_low_confidence(cfg):
    result = detect_expected_count("Details", [], [], None, cfg)
    assert result.count is None
    assert result.source == CountSource.UNKNOWN
    assert result.confidence == pytest.approx(0.20)


def test_at_least_phrase_sets_min_bound(cfg):
    result = detect_expected_count("Provide at least 5 photographs", [], [], None, cfg)
    assert result.count == 5
    assert result.bound == "min"


# ============================================================================
# Bound variants and number words
# ============================================================================


def test_up_to_phrase_sets_max_bound(cfg):
    result = detect_expected_count("Attach up to 5 documents", [], [], None, cfg)
    assert result.count == 5
    assert result.bound == "max"


def test_number_words_are_normalized(cfg):
    result = detect_expected_count("Provide ten contact numbers", [], [], None, cfg)
    assert result.count == 10
    assert result.source == CountSource.EXPLICIT_INSTRUCTION


def test_parenthetical_quantity(cfg):
    result = detect_expected_count("Contact Numbers (10)", [], [], None, cfg)
    assert result.count == 10


# ============================================================================
# Table rows (S.No.-style column proxy)
# ============================================================================


def test_table_rows_sequential_sno_column(cfg):
    header = _mk_cell(row=1, col=2, text="Compensation Amount")
    sno_cells = [_mk_cell(row=r, col=1, text=str(r - 1)) for r in range(2, 12)]  # rows 2..11 -> 1..10
    sheet_cells = [header] + sno_cells
    result = detect_expected_count("Compensation Amount", [], sheet_cells, header, cfg)
    assert result.count == 10
    assert result.source == CountSource.TABLE_ROWS


# ============================================================================
# Data validation constraint
# ============================================================================


def test_data_validation_max_constraint(cfg):
    cell = _mk_cell(row=1, col=1, text="", data_validation="<=10")
    result = detect_expected_count("Items", [], [], cell, cfg)
    assert result.count == 10
    assert result.source == CountSource.DATA_VALIDATION
    assert result.bound == "max"


# ============================================================================
# Singular-label heuristic: opt-in, and gated by min_confidence_to_accept too
# ============================================================================


def test_singular_label_disabled_by_default(cfg):
    result = detect_expected_count("Project Name", [], [], None, cfg)
    assert result.count is None
    assert result.source == CountSource.UNKNOWN


def test_singular_label_requires_both_flags_to_cooperate():
    # assume_single_when_unknown alone isn't enough: SINGULAR_LABEL's fixed
    # 0.55 confidence still needs min_confidence_to_accept lowered to admit it.
    cfg_flag_only = load_config(overrides={"expected_count": {"assume_single_when_unknown": True}})
    result = detect_expected_count("Project Name", [], [], None, cfg_flag_only)
    assert result.count is None

    cfg_both = load_config(
        overrides={"expected_count": {"assume_single_when_unknown": True, "min_confidence_to_accept": 0.5}}
    )
    result = detect_expected_count("Project Name", [], [], None, cfg_both)
    assert result.count == 1
    assert result.source == CountSource.SINGULAR_LABEL


def test_singular_label_skips_plural_looking_labels():
    cfg = load_config(
        overrides={"expected_count": {"assume_single_when_unknown": True, "min_confidence_to_accept": 0.5}}
    )
    result = detect_expected_count("Contractors", [], [], None, cfg)
    assert result.count is None


# ============================================================================
# Never invent a number
# ============================================================================


def test_count_above_max_sane_count_is_rejected():
    cfg = load_config(overrides={"expected_count": {"max_sane_count": 50}})
    result = detect_expected_count("Provide 100 photographs", [], [], None, cfg)
    assert result.count is None
    assert result.source == CountSource.UNKNOWN


def test_malformed_range_lo_greater_than_hi_is_rejected(cfg):
    result = detect_expected_count("S.No. 10-1", [], [], None, cfg)
    assert result.count is None
    assert result.source == CountSource.UNKNOWN


def test_enumerated_labels_below_minimum_run_length_is_rejected(cfg):
    # Only 2 members -- below the >=3 threshold that guards against false positives.
    sheet_cells = [_mk_cell(row=1, col=1, text="Person 1"), _mk_cell(row=2, col=1, text="Person 2")]
    result = detect_expected_count("Affected Persons", [], sheet_cells, sheet_cells[0], cfg)
    assert result.count is None
    assert result.source == CountSource.UNKNOWN
