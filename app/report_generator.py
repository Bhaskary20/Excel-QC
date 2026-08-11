"""QCRun -> QC_Report.xlsx, the four sheets from BUILD_PLAN.md Phase 11 /
the original spec's §20: Summary, Cell Analysis, Value Analysis, Sheet
Summary. Pure presentation layer -- no QC logic lives here.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.config import Config
from app.models import QCRun, Status

_HEADER_FILL = PatternFill(start_color="FF2F5496", end_color="FF2F5496", fill_type="solid")
_HEADER_FONT = Font(bold=True, color="FFFFFFFF")
_PERCENT_FORMAT = "0.0%"
_MAX_COL_WIDTH = 60

# (fill, font) per status -- light background + dark text for the "ok-ish"
# statuses (standard Excel conditional-formatting palette), a stronger dark
# red for INVALID so it reads as more severe than MISSING at a glance.
_STATUS_STYLES: dict[Status, tuple[PatternFill, Font]] = {
    Status.COMPLETE: (
        PatternFill(start_color="FFC6EFCE", end_color="FFC6EFCE", fill_type="solid"),
        Font(color="FF006100"),
    ),
    Status.PARTIAL: (
        PatternFill(start_color="FFFFEB9C", end_color="FFFFEB9C", fill_type="solid"),
        Font(color="FF9C6500"),
    ),
    Status.MISSING: (
        PatternFill(start_color="FFFFC7CE", end_color="FFFFC7CE", fill_type="solid"),
        Font(color="FF9C0006"),
    ),
    Status.INVALID: (
        PatternFill(start_color="FFC00000", end_color="FFC00000", fill_type="solid"),
        Font(color="FFFFFFFF"),
    ),
    Status.REVIEW: (
        PatternFill(start_color="FFBDD7EE", end_color="FFBDD7EE", fill_type="solid"),
        Font(color="FF1F4E78"),
    ),
    Status.NOT_APPLICABLE: (
        PatternFill(start_color="FFD9D9D9", end_color="FFD9D9D9", fill_type="solid"),
        Font(color="FF404040"),
    ),
}

_CELL_ANALYSIS_HEADERS = [
    "Sheet", "Cell", "Field / Column", "Field Type", "Expected Count", "Detected Count",
    "Valid Count", "Invalid Count", "Missing Count", "Completeness %", "Status", "Confidence", "Reason",
]
_VALUE_ANALYSIS_HEADERS = ["Sheet", "Cell", "Field", "Value", "Value Index", "Validation Status", "Reason"]
_SHEET_SUMMARY_HEADERS = [
    "Sheet", "Expected Responses", "Valid Responses", "Missing", "Invalid",
    "Partial Cells", "Complete Cells", "Completeness %",
]


def _mask_value(value: str) -> str:
    """'9876543210' -> '98765*****' -- first 5 chars visible, rest masked."""
    if not value:
        return value
    visible = min(5, len(value))
    return value[:visible] + "*" * (len(value) - visible)


def _write_header_row(ws: Worksheet, headers: list[str]) -> None:
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _apply_status_style(ws: Worksheet, row_idx: int, num_cols: int, status: Status) -> None:
    style = _STATUS_STYLES.get(status)
    if style is None:
        return
    fill, font = style
    for col_idx in range(1, num_cols + 1):
        cell = ws.cell(row=row_idx, column=col_idx)
        cell.fill = fill
        cell.font = font


def _autosize_columns(ws: Worksheet, num_cols: int) -> None:
    for col_idx in range(1, num_cols + 1):
        col_letter = get_column_letter(col_idx)
        max_length = max((len(str(c.value)) for c in ws[col_letter] if c.value is not None), default=0)
        ws.column_dimensions[col_letter].width = min(max(max_length + 2, 10), _MAX_COL_WIDTH)


def _finalize_sheet(ws: Worksheet, num_cols: int, num_data_rows: int, cfg: Config) -> None:
    if cfg.report.freeze_header_row:
        ws.freeze_panes = "A2"
    if cfg.report.autofilter and num_data_rows > 0:
        ws.auto_filter.ref = f"A1:{get_column_letter(num_cols)}{num_data_rows + 1}"
    _autosize_columns(ws, num_cols)


def _write_summary_sheet(ws: Worksheet, run: QCRun) -> None:
    s = run.workbook_summary

    ws["A1"] = "QC Report Summary"
    ws["A1"].font = Font(bold=True, size=14)

    row = 3
    for label, value in [
        ("Template", run.template_path),
        ("Response", run.response_path),
        ("Generated at", run.generated_at.isoformat(sep=" ", timespec="seconds")),
        ("Engine version", run.engine_version),
        ("AI enabled", "Yes" if run.ai_enabled else "No"),
    ]:
        ws.cell(row=row, column=1, value=label).font = Font(bold=True)
        ws.cell(row=row, column=2, value=value)
        row += 1

    row += 1
    for label, value in [
        ("Total Sheets", s.total_sheets),
        ("Total Cells Checked", s.total_cells_checked),
        ("Total Expected Responses", s.total_expected),
        ("Total Valid Responses", s.total_valid),
        ("Total Missing Responses", s.total_missing),
        ("Total Invalid Responses", s.total_invalid),
        ("Complete Cells", s.complete_cells),
        ("Partial Cells", s.partial_cells),
        ("Missing Cells", s.missing_cells),
        ("Invalid Cells", s.invalid_cells),
        ("Review Cells", s.review_cells),
        ("Not Applicable Cells", s.not_applicable_cells),
    ]:
        ws.cell(row=row, column=1, value=label).font = Font(bold=True)
        ws.cell(row=row, column=2, value=value)
        row += 1

    ws.cell(row=row, column=1, value="Overall Completeness %").font = Font(bold=True)
    completeness_cell = ws.cell(row=row, column=2, value=s.overall_completeness)
    if s.overall_completeness is not None:
        completeness_cell.number_format = _PERCENT_FORMAT

    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 40


def _write_cell_analysis_sheet(ws: Worksheet, run: QCRun, cfg: Config) -> None:
    _write_header_row(ws, _CELL_ANALYSIS_HEADERS)

    for row_idx, r in enumerate(run.results, start=2):
        ws.cell(row=row_idx, column=1, value=r.sheet)
        ws.cell(row=row_idx, column=2, value=r.cell)
        ws.cell(row=row_idx, column=3, value=r.field_name)
        ws.cell(row=row_idx, column=4, value=r.field_type.value)
        ws.cell(row=row_idx, column=5, value=r.expected_count if r.expected_count is not None else "UNKNOWN")
        ws.cell(row=row_idx, column=6, value=r.detected_count)
        ws.cell(row=row_idx, column=7, value=r.valid_count)
        ws.cell(row=row_idx, column=8, value=r.invalid_count)
        ws.cell(row=row_idx, column=9, value=r.missing_count if r.missing_count is not None else "UNKNOWN")
        completeness_cell = ws.cell(row=row_idx, column=10, value=r.completeness)
        if r.completeness is not None:
            completeness_cell.number_format = _PERCENT_FORMAT
        ws.cell(row=row_idx, column=11, value=r.status.value)
        ws.cell(row=row_idx, column=12, value=round(r.confidence, 2))
        ws.cell(row=row_idx, column=13, value=r.reason)

        _apply_status_style(ws, row_idx, len(_CELL_ANALYSIS_HEADERS), r.status)

    _finalize_sheet(ws, len(_CELL_ANALYSIS_HEADERS), len(run.results), cfg)


def _write_value_analysis_sheet(ws: Worksheet, run: QCRun, cfg: Config) -> None:
    _write_header_row(ws, _VALUE_ANALYSIS_HEADERS)

    row_idx = 2
    for r in run.results:
        for pv in r.values:
            display_value = _mask_value(pv.raw) if cfg.security.redact_in_reports else pv.raw
            ws.cell(row=row_idx, column=1, value=r.sheet)
            ws.cell(row=row_idx, column=2, value=r.cell)
            ws.cell(row=row_idx, column=3, value=r.field_name)
            ws.cell(row=row_idx, column=4, value=display_value)
            ws.cell(row=row_idx, column=5, value=pv.index)
            ws.cell(row=row_idx, column=6, value="VALID" if pv.verdict.is_valid else "INVALID")
            ws.cell(row=row_idx, column=7, value=pv.verdict.reason)
            row_idx += 1

    _finalize_sheet(ws, len(_VALUE_ANALYSIS_HEADERS), row_idx - 2, cfg)


def _write_sheet_summary_sheet(ws: Worksheet, run: QCRun, cfg: Config) -> None:
    _write_header_row(ws, _SHEET_SUMMARY_HEADERS)

    for row_idx, s in enumerate(run.sheet_summaries, start=2):
        ws.cell(row=row_idx, column=1, value=s.sheet)
        ws.cell(row=row_idx, column=2, value=s.expected_responses)
        ws.cell(row=row_idx, column=3, value=s.valid_responses)
        ws.cell(row=row_idx, column=4, value=s.missing)
        ws.cell(row=row_idx, column=5, value=s.invalid)
        ws.cell(row=row_idx, column=6, value=s.partial_cells)
        ws.cell(row=row_idx, column=7, value=s.complete_cells)
        completeness_cell = ws.cell(row=row_idx, column=8, value=s.completeness)
        if s.completeness is not None:
            completeness_cell.number_format = _PERCENT_FORMAT

    _finalize_sheet(ws, len(_SHEET_SUMMARY_HEADERS), len(run.sheet_summaries), cfg)


def generate_report(run: QCRun, output_path: str, cfg: Config) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    _write_summary_sheet(wb.create_sheet("Summary"), run)
    _write_cell_analysis_sheet(wb.create_sheet("Cell Analysis"), run, cfg)
    _write_value_analysis_sheet(wb.create_sheet("Value Analysis"), run, cfg)
    _write_sheet_summary_sheet(wb.create_sheet("Sheet Summary"), run, cfg)

    output_dir = Path(output_path).parent
    if output_dir and not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)

    wb.save(output_path)
