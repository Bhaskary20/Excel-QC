"""Phase 11 gate: all four sheets present with exact headers, the file
round-trips through openpyxl cleanly, and completeness is a real number
(not a string) so it sorts/filters correctly in Excel."""

import openpyxl
import pytest

from app.config import load_config
from app.models import (
    CountSource,
    ExpectedCount,
    FieldType,
    ParsedValue,
    QCResult,
    QCRun,
    SheetSummary,
    Status,
    ValueVerdict,
    WorkbookSummary,
)
from app.report_generator import generate_report


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _sample_run() -> QCRun:
    contact_values = [
        ParsedValue(index=1, raw="9876543210", verdict=ValueVerdict(is_valid=True, normalized="9876543210")),
        ParsedValue(index=2, raw="9876", verdict=ValueVerdict(is_valid=False, normalized=None, reason="expected 10 digits, got 4")),
    ]
    results = [
        QCResult(
            sheet="Contact Details", cell="D15", field_name="Contact Numbers", field_type=FieldType.PHONE,
            expected_count=10, detected_count=2, valid_count=1, invalid_count=1, missing_count=9,
            completeness=0.1, status=Status.PARTIAL, confidence=0.95,
            reason="1 valid of 10 expected; 9 missing", values=contact_values,
        ),
        QCResult(
            sheet="Contact Details", cell="D20", field_name="Project Name", field_type=FieldType.NAME,
            expected_count=1, detected_count=1, valid_count=1, invalid_count=0, missing_count=0,
            completeness=1.0, status=Status.COMPLETE, confidence=1.0,
            reason="all 1 expected values valid",
            values=[ParsedValue(index=1, raw="Rahul Sharma", verdict=ValueVerdict(is_valid=True, normalized="Rahul Sharma"))],
        ),
        QCResult(
            sheet="Financials", cell="B5", field_name="Details", field_type=FieldType.UNKNOWN,
            expected_count=None, detected_count=0, valid_count=0, invalid_count=0, missing_count=None,
            completeness=None, status=Status.REVIEW, confidence=0.20,
            reason="expected count unknown", values=[],
        ),
    ]
    sheet_summaries = [
        SheetSummary(
            sheet="Contact Details", expected_responses=11, valid_responses=2, missing=9, invalid=1,
            partial_cells=1, complete_cells=1, completeness=2 / 11,
        ),
        SheetSummary(
            sheet="Financials", expected_responses=0, valid_responses=0, missing=0, invalid=0,
            partial_cells=0, complete_cells=0, completeness=None,
        ),
    ]
    workbook_summary = WorkbookSummary(
        total_sheets=2, total_cells_checked=3, total_expected=11, total_valid=2, total_missing=9,
        total_invalid=1, complete_cells=1, partial_cells=1, missing_cells=0, invalid_cells=0,
        review_cells=1, not_applicable_cells=0, overall_completeness=2 / 11,
    )
    return QCRun(
        template_path="template.xlsx", response_path="response.xlsx",
        results=results, sheet_summaries=sheet_summaries, workbook_summary=workbook_summary,
        extra_response_cells=["Contact Details!Z1"],
    )


def _generate(run, cfg, tmp_path, name="QC_Report.xlsx"):
    output = tmp_path / name
    generate_report(run, str(output), cfg)
    return output


# ============================================================================
# Structure: all four sheets, exact headers, valid file
# ============================================================================


def test_report_generates_all_four_sheets_in_order(cfg, tmp_path):
    output = _generate(_sample_run(), cfg, tmp_path)
    wb = openpyxl.load_workbook(output)
    assert wb.sheetnames == ["Summary", "Cell Analysis", "Value Analysis", "Sheet Summary"]


def test_cell_analysis_headers_exact(cfg, tmp_path):
    output = _generate(_sample_run(), cfg, tmp_path)
    ws = openpyxl.load_workbook(output)["Cell Analysis"]
    headers = [c.value for c in ws[1]]
    assert headers == [
        "Sheet", "Cell", "Field / Column", "Field Type", "Expected Count", "Detected Count",
        "Valid Count", "Invalid Count", "Missing Count", "Completeness %", "Status", "Confidence", "Reason",
    ]


def test_value_analysis_headers_exact(cfg, tmp_path):
    output = _generate(_sample_run(), cfg, tmp_path)
    ws = openpyxl.load_workbook(output)["Value Analysis"]
    headers = [c.value for c in ws[1]]
    assert headers == ["Sheet", "Cell", "Field", "Value", "Value Index", "Validation Status", "Reason"]


def test_sheet_summary_headers_exact(cfg, tmp_path):
    output = _generate(_sample_run(), cfg, tmp_path)
    ws = openpyxl.load_workbook(output)["Sheet Summary"]
    headers = [c.value for c in ws[1]]
    assert headers == [
        "Sheet", "Expected Responses", "Valid Responses", "Missing", "Invalid",
        "Partial Cells", "Complete Cells", "Completeness %",
    ]


# ============================================================================
# Content correctness
# ============================================================================


def test_completeness_is_numeric_with_percent_format(cfg, tmp_path):
    output = _generate(_sample_run(), cfg, tmp_path)
    ws = openpyxl.load_workbook(output)["Cell Analysis"]
    cell = ws.cell(row=2, column=10)  # Contact Numbers row, completeness=0.1
    assert isinstance(cell.value, float)
    assert cell.value == pytest.approx(0.1)
    assert cell.number_format == "0.0%"


def test_unknown_expected_count_shown_as_unknown_not_blank(cfg, tmp_path):
    output = _generate(_sample_run(), cfg, tmp_path)
    ws = openpyxl.load_workbook(output)["Cell Analysis"]
    assert ws.cell(row=4, column=5).value == "UNKNOWN"  # Details row, expected_count=None
    assert ws.cell(row=4, column=9).value == "UNKNOWN"  # missing_count=None too


def test_value_analysis_has_one_row_per_parsed_value(cfg, tmp_path):
    output = _generate(_sample_run(), cfg, tmp_path)
    ws = openpyxl.load_workbook(output)["Value Analysis"]
    # 2 values (Contact Numbers) + 1 (Project Name) + 0 (Details) = 3 data rows
    assert ws.max_row == 4


def test_value_analysis_validation_status_strings(cfg, tmp_path):
    output = _generate(_sample_run(), cfg, tmp_path)
    ws = openpyxl.load_workbook(output)["Value Analysis"]
    statuses = [ws.cell(row=r, column=6).value for r in range(2, ws.max_row + 1)]
    assert statuses == ["VALID", "INVALID", "VALID"]


def test_summary_sheet_has_key_metrics(cfg, tmp_path):
    output = _generate(_sample_run(), cfg, tmp_path)
    ws = openpyxl.load_workbook(output)["Summary"]
    labels = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
    assert "Total Sheets" in labels
    assert "Overall Completeness %" in labels
    assert "Template" in labels


# ============================================================================
# Redaction
# ============================================================================


def test_no_redaction_by_default(cfg, tmp_path):
    output = _generate(_sample_run(), cfg, tmp_path)
    ws = openpyxl.load_workbook(output)["Value Analysis"]
    values = [ws.cell(row=r, column=4).value for r in range(2, ws.max_row + 1)]
    assert "9876543210" in values


def test_redaction_masks_values_when_enabled(tmp_path):
    cfg = load_config(overrides={"security": {"redact_in_reports": True}})
    output = _generate(_sample_run(), cfg, tmp_path)
    ws = openpyxl.load_workbook(output)["Value Analysis"]
    values = [ws.cell(row=r, column=4).value for r in range(2, ws.max_row + 1)]
    assert "9876543210" not in values
    assert "98765*****" in values


# ============================================================================
# Formatting
# ============================================================================


def test_status_fill_applied_to_complete_row(cfg, tmp_path):
    output = _generate(_sample_run(), cfg, tmp_path)
    ws = openpyxl.load_workbook(output)["Cell Analysis"]
    fill = ws.cell(row=3, column=1).fill  # Project Name row, status=COMPLETE
    assert fill.start_color.rgb == "FFC6EFCE"


def test_freeze_panes_and_autofilter_set(cfg, tmp_path):
    output = _generate(_sample_run(), cfg, tmp_path)
    ws = openpyxl.load_workbook(output)["Cell Analysis"]
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref is not None


def test_output_directory_created_if_missing(cfg, tmp_path):
    output = tmp_path / "nested" / "dir" / "QC_Report.xlsx"
    generate_report(_sample_run(), str(output), cfg)
    assert output.exists()


def test_empty_run_does_not_crash(cfg, tmp_path):
    empty_run = QCRun(
        template_path="t.xlsx", response_path="r.xlsx",
        results=[], sheet_summaries=[], workbook_summary=WorkbookSummary(),
    )
    output = _generate(empty_run, cfg, tmp_path, name="empty.xlsx")
    wb = openpyxl.load_workbook(output)
    assert wb.sheetnames == ["Summary", "Cell Analysis", "Value Analysis", "Sheet Summary"]
