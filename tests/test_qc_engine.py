"""Phase 10 gate: every row of the 12-row status table, the 2 worked
examples from BUILD_PLAN.md (Phase 10 and Phase 19) reproduced exactly,
plus evaluate_field/run_qc_from_specs integration and aggregation."""

import pytest

import app.validators  # noqa: F401 -- real validators needed for integration tests
from app.config import load_config
from app.excel_reader import CellRecord
from app.field_matcher import FieldMatch
from app.models import CountSource, ExpectedCount, FieldSpec, FieldType, Status
from app.qc_engine import decide_status, evaluate_field, run_qc_from_specs


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _spec(expected_count=10, bound="exact", required=True, field_type=FieldType.PHONE, confidence=1.0) -> FieldSpec:
    return FieldSpec(
        sheet="Sheet1",
        cell="D15",
        field_name="Contact Numbers",
        field_type=field_type,
        field_type_confidence=confidence,
        expected=ExpectedCount(count=expected_count, source=CountSource.EXPLICIT_INSTRUCTION, confidence=confidence, bound=bound),
        required=required,
        source="test",
        context_text="",
    )


def _cell(text, sheet="Sheet1", cell="D15", row=15, col=4) -> CellRecord:
    return CellRecord(
        sheet=sheet, cell=cell, row=row, col=col, raw_value=text or None, text=text,
        is_merged=False, merge_anchor=None, number_format="General", is_bold=False,
        has_comment=False, comment_text=None, data_validation=None,
    )


# ============================================================================
# The 2 Done-when worked examples, verbatim, via decide_status directly
# ============================================================================


def test_phase13_worked_example(cfg):
    spec = _spec(expected_count=10)
    status, completeness, reason = decide_status(10, 6, 5, 1, spec, cfg)
    assert status == Status.PARTIAL
    assert completeness == pytest.approx(0.50)


def test_phase19_worked_example(cfg):
    spec = _spec(expected_count=10)
    status, completeness, reason = decide_status(10, 6, 6, 0, spec, cfg)
    assert status == Status.PARTIAL
    assert completeness == pytest.approx(0.60)


# ============================================================================
# All 12 table rows
# ============================================================================


def test_row1_cell_not_found(cfg):
    status, completeness, reason = decide_status(10, 0, 0, 0, _spec(), cfg, cell_found=False)
    assert status == Status.MISSING
    assert completeness == 0.0


def test_row2_marked_not_applicable(cfg):
    status, completeness, reason = decide_status(10, 0, 0, 0, _spec(), cfg, is_marked_na=True)
    assert status == Status.NOT_APPLICABLE
    assert completeness is None


def test_row3_blank_and_required(cfg):
    status, completeness, reason = decide_status(10, 0, 0, 0, _spec(required=True), cfg)
    assert status == Status.MISSING
    assert completeness == 0.0


def test_row4_blank_and_optional_default(cfg):
    status, completeness, reason = decide_status(10, 0, 0, 0, _spec(required=False), cfg)
    assert status == Status.MISSING  # default treat_blank_optional_as
    assert completeness == 0.0


def test_row4_blank_and_optional_as_not_applicable():
    cfg = load_config(overrides={"status": {"treat_blank_optional_as": "NOT_APPLICABLE"}})
    status, completeness, reason = decide_status(10, 0, 0, 0, _spec(required=False), cfg)
    assert status == Status.NOT_APPLICABLE


def test_row5_unknown_expected_none_valid(cfg):
    status, completeness, reason = decide_status(None, 3, 0, 3, _spec(expected_count=None), cfg)
    assert status == Status.INVALID
    assert completeness is None


def test_row6_unknown_expected_some_valid(cfg):
    status, completeness, reason = decide_status(None, 3, 2, 1, _spec(expected_count=None), cfg)
    assert status == Status.REVIEW
    assert completeness is None


def test_row7_known_expected_none_valid(cfg):
    status, completeness, reason = decide_status(10, 3, 0, 3, _spec(), cfg)
    assert status == Status.INVALID
    assert completeness == 0.0


def test_row8_max_bound_within_limit(cfg):
    status, completeness, reason = decide_status(5, 3, 3, 0, _spec(expected_count=5, bound="max"), cfg)
    assert status == Status.COMPLETE
    assert completeness == pytest.approx(0.6)


def test_row9_oversupply_is_review_when_configured():
    cfg = load_config(overrides={"status": {"oversupply_is_review": True}})
    status, completeness, reason = decide_status(10, 12, 12, 0, _spec(expected_count=10), cfg)
    assert status == Status.REVIEW
    assert completeness == 1.0


def test_row10_exact_match_is_complete(cfg):
    status, completeness, reason = decide_status(10, 10, 10, 0, _spec(expected_count=10), cfg)
    assert status == Status.COMPLETE
    assert completeness == 1.0


def test_row10_oversupply_is_complete_by_default(cfg):
    status, completeness, reason = decide_status(10, 12, 12, 0, _spec(expected_count=10), cfg)
    assert status == Status.COMPLETE
    assert completeness == 1.0


def test_row11_partial(cfg):
    status, completeness, reason = decide_status(10, 6, 5, 1, _spec(expected_count=10), cfg)
    assert status == Status.PARTIAL
    assert completeness == pytest.approx(0.5)
    assert "5 valid of 10 expected" in reason


def test_row12_fallback_never_crashes_on_broken_invariants(cfg):
    # V negative should never occur in practice (D >= V + I, V >= 0 always
    # holds upstream) -- this only proves the fallback doesn't crash if it did.
    status, completeness, reason = decide_status(10, 5, -1, 6, _spec(expected_count=10), cfg)
    assert status == Status.REVIEW


# ============================================================================
# evaluate_field: confidence computation and the low-confidence upgrade
# ============================================================================


def test_evaluate_field_complete_case(cfg):
    spec = _spec(expected_count=1, field_type=FieldType.NAME)
    cell = _cell("Rahul Sharma")
    match = FieldMatch(spec=spec, cell=cell, strategy="exact_coordinate")
    result = evaluate_field(match, cfg)
    assert result.status == Status.COMPLETE
    assert result.expected_count == 1
    assert result.valid_count == 1


def test_evaluate_field_low_confidence_upgrades_to_review():
    cfg = load_config()
    spec = _spec(expected_count=10, confidence=0.3)  # both field_type_confidence and expected.confidence = 0.3
    cell = _cell("9876543210\n9876543211\n9876543212\n9876543213\n9876543214\n9876543215\n9876543216\n9876543217\n9876543218\n9876543219")
    match = FieldMatch(spec=spec, cell=cell, strategy="exact_coordinate")
    result = evaluate_field(match, cfg)
    assert result.status == Status.REVIEW
    assert result.confidence < cfg.status.low_confidence_review_threshold


def test_evaluate_field_missing_is_never_upgraded_despite_low_confidence(cfg):
    spec = _spec(expected_count=10, confidence=0.1)
    match = FieldMatch(spec=spec, cell=None, strategy="unmatched")
    result = evaluate_field(match, cfg)
    assert result.status == Status.MISSING


def test_evaluate_field_fallback_strategy_reduces_confidence(cfg):
    spec = _spec(expected_count=1, field_type=FieldType.NAME, confidence=1.0)
    cell = _cell("Rahul Sharma")
    exact_match = FieldMatch(spec=spec, cell=cell, strategy="exact_coordinate")
    offset_match = FieldMatch(spec=spec, cell=cell, strategy="row_offset")
    exact_result = evaluate_field(exact_match, cfg)
    offset_result = evaluate_field(offset_match, cfg)
    assert offset_result.confidence < exact_result.confidence


def test_evaluate_field_not_applicable(cfg):
    spec = _spec(expected_count=10)
    cell = _cell("N/A")
    match = FieldMatch(spec=spec, cell=cell, strategy="exact_coordinate")
    result = evaluate_field(match, cfg)
    assert result.status == Status.NOT_APPLICABLE
    assert result.detected_count == 0


def test_evaluate_field_duplicates_reduce_valid_count(cfg):
    spec = _spec(expected_count=5)
    cell = _cell("\n".join(["9876543210"] * 5))
    match = FieldMatch(spec=spec, cell=cell, strategy="exact_coordinate")
    result = evaluate_field(match, cfg)
    assert result.valid_count == 1
    assert result.invalid_count == 4
    assert result.status == Status.PARTIAL


# ============================================================================
# run_qc_from_specs: end-to-end with aggregation
# ============================================================================


def test_run_qc_from_specs_end_to_end_aggregation(cfg):
    specs = [
        FieldSpec(
            sheet="Sheet1", cell="A1", field_name="Project Name", field_type=FieldType.NAME,
            field_type_confidence=1.0,
            expected=ExpectedCount(count=1, source=CountSource.EXPLICIT_INSTRUCTION, confidence=0.95),
            required=True, source="test", context_text="",
        ),
        FieldSpec(
            sheet="Sheet1", cell="A2", field_name="Contact Numbers", field_type=FieldType.PHONE,
            field_type_confidence=1.0,
            expected=ExpectedCount(count=10, source=CountSource.EXPLICIT_INSTRUCTION, confidence=0.95),
            required=True, source="test", context_text="",
        ),
    ]
    response_cells = [
        _cell("Nellore Bypass Widening", cell="A1", row=1, col=1),
        _cell("9876543210\n9876543211\n9876543212\n9876543213\n9876543214\n9876543215", cell="A2", row=2, col=1),
    ]

    run = run_qc_from_specs(specs, response_cells, cfg)

    assert len(run.results) == 2
    by_name = {r.field_name: r for r in run.results}
    assert by_name["Project Name"].status == Status.COMPLETE
    assert by_name["Contact Numbers"].status == Status.PARTIAL
    assert by_name["Contact Numbers"].valid_count == 6
    assert by_name["Contact Numbers"].missing_count == 4

    assert run.workbook_summary.total_sheets == 1
    assert run.workbook_summary.total_cells_checked == 2
    assert run.workbook_summary.total_expected == 11  # 1 + 10
    assert run.workbook_summary.total_valid == 7  # 1 + 6
    assert run.workbook_summary.complete_cells == 1
    assert run.workbook_summary.partial_cells == 1
    assert run.workbook_summary.overall_completeness == pytest.approx(7 / 11)

    assert len(run.sheet_summaries) == 1
    assert run.sheet_summaries[0].sheet == "Sheet1"
    assert run.sheet_summaries[0].expected_responses == 11
    assert run.sheet_summaries[0].valid_responses == 7


def test_run_qc_from_specs_missing_field(cfg):
    specs = [
        FieldSpec(
            sheet="Sheet1", cell="A1", field_name="Project Name", field_type=FieldType.NAME,
            field_type_confidence=1.0,
            expected=ExpectedCount(count=1, source=CountSource.EXPLICIT_INSTRUCTION, confidence=0.95),
            required=True, source="test", context_text="",
        )
    ]
    run = run_qc_from_specs(specs, [], cfg)
    assert run.results[0].status == Status.MISSING
    assert run.workbook_summary.missing_cells == 1


def test_review_cells_excluded_from_completeness_denominator(cfg):
    specs = [
        FieldSpec(
            sheet="Sheet1", cell="A1", field_name="Details", field_type=FieldType.TEXT,
            field_type_confidence=0.0,
            expected=ExpectedCount(count=None, source=CountSource.UNKNOWN, confidence=0.20),
            required=True, source="test", context_text="",
        )
    ]
    response_cells = [_cell("some free text response", cell="A1", row=1, col=1)]
    run = run_qc_from_specs(specs, response_cells, cfg)
    assert run.results[0].status == Status.REVIEW
    assert run.workbook_summary.total_expected == 0
    assert run.workbook_summary.overall_completeness is None
    assert run.workbook_summary.review_cells == 1
