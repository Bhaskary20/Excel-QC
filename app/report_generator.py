"""QCRun -> QC_Report.xlsx, the five sheets from BUILD_PLAN.md v2 Section 7
Phase H: Summary, Row Analysis, Cell Analysis, Slot Analysis, Consistency
Findings. Pure presentation layer -- no QC logic lives here.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.config import Config
from app.consistency_checker import STATUS_SEVERITY
from app.models import QCRun, RowResult, Status

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

_ROW_ANALYSIS_HEADERS = [
    "S.No", "Plaza Code", "Plaza Name", "RO", "PIU", "Match Strategy",
    "Agencies (N)", "Row Status", "Completeness %", "Problem Columns", "Identity Mismatches",
]
_CELL_ANALYSIS_HEADERS = [
    "S.No", "Plaza Name", "Column", "Field Name", "Expected Count", "Detected Count",
    "Valid Count", "Invalid Count", "Missing Slots", "Completeness %", "Status", "Reason",
]
_SLOT_ANALYSIS_HEADERS = [
    "S.No", "Plaza Name", "Column", "Field Name", "Slot #", "Value", "Validation Status", "Reason",
]
_CONSISTENCY_HEADERS = ["S.No", "Plaza Name", "Column", "Kind", "Severity", "Message"]

_NON_ISSUE_STATUSES = {Status.COMPLETE, Status.NOT_APPLICABLE}


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
    ]:
        ws.cell(row=row, column=1, value=label).font = Font(bold=True)
        ws.cell(row=row, column=2, value=value)
        row += 1

    row += 1
    for label, value in [
        ("Total Rows", s.total_rows),
        ("Total Cells Checked", s.total_cells_checked),
        ("Total Expected Slots", s.total_expected_slots),
        ("Total Valid Slots", s.total_valid_slots),
        ("Total Missing Slots", s.total_missing_slots),
        ("Total Invalid Slots", s.total_invalid_slots),
        ("Complete Cells", s.complete_cells),
        ("Partial Cells", s.partial_cells),
        ("Missing Cells", s.missing_cells),
        ("Invalid Cells", s.invalid_cells),
        ("Review Cells", s.review_cells),
        ("Not Applicable Cells", s.not_applicable_cells),
        ("Complete Rows", s.complete_rows),
        ("Partial Rows", s.partial_rows),
        ("Missing Rows", s.missing_rows),
        ("Invalid Rows", s.invalid_rows),
        ("Review Rows", s.review_rows),
        ("Not Applicable Rows", s.not_applicable_rows),
        ("Total Consistency Findings", s.total_consistency_findings),
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


def _write_row_analysis_sheet(ws: Worksheet, run: QCRun, cfg: Config) -> None:
    _write_header_row(ws, _ROW_ANALYSIS_HEADERS)

    for row_idx, r in enumerate(run.rows, start=2):
        problem_columns = sum(1 for cr in r.per_column.values() if cr.status not in _NON_ISSUE_STATUSES)

        ws.cell(row=row_idx, column=1, value=r.s_no)
        ws.cell(row=row_idx, column=2, value=r.plaza_code)
        ws.cell(row=row_idx, column=3, value=r.plaza_name)
        ws.cell(row=row_idx, column=4, value=r.ro)
        ws.cell(row=row_idx, column=5, value=r.piu)
        ws.cell(row=row_idx, column=6, value=r.match_strategy)
        ws.cell(row=row_idx, column=7, value=r.n_contracts)
        ws.cell(row=row_idx, column=8, value=r.status.value)
        completeness_cell = ws.cell(row=row_idx, column=9, value=r.completeness)
        if r.completeness is not None:
            completeness_cell.number_format = _PERCENT_FORMAT
        ws.cell(row=row_idx, column=10, value=problem_columns)
        ws.cell(row=row_idx, column=11, value="; ".join(r.identity_mismatches))

        _apply_status_style(ws, row_idx, len(_ROW_ANALYSIS_HEADERS), r.status)

    _finalize_sheet(ws, len(_ROW_ANALYSIS_HEADERS), len(run.rows), cfg)


def _write_cell_analysis_sheet(ws: Worksheet, run: QCRun, cfg: Config) -> None:
    _write_header_row(ws, _CELL_ANALYSIS_HEADERS)

    row_idx = 2
    for r in run.rows:
        for column_letter, cr in r.per_column.items():
            ws.cell(row=row_idx, column=1, value=r.s_no)
            ws.cell(row=row_idx, column=2, value=r.plaza_name)
            ws.cell(row=row_idx, column=3, value=column_letter)
            ws.cell(row=row_idx, column=4, value=cr.field_name)
            ws.cell(row=row_idx, column=5, value=cr.expected_count if cr.expected_count is not None else "UNKNOWN")
            ws.cell(row=row_idx, column=6, value=cr.detected_count)
            ws.cell(row=row_idx, column=7, value=cr.valid_count)
            ws.cell(row=row_idx, column=8, value=cr.invalid_count)
            ws.cell(row=row_idx, column=9, value=", ".join(str(s) for s in cr.missing_slots))
            completeness_cell = ws.cell(row=row_idx, column=10, value=cr.completeness)
            if cr.completeness is not None:
                completeness_cell.number_format = _PERCENT_FORMAT
            ws.cell(row=row_idx, column=11, value=cr.status.value)
            ws.cell(row=row_idx, column=12, value=cr.reason)

            _apply_status_style(ws, row_idx, len(_CELL_ANALYSIS_HEADERS), cr.status)
            row_idx += 1

    _finalize_sheet(ws, len(_CELL_ANALYSIS_HEADERS), row_idx - 2, cfg)


def _write_slot_analysis_sheet(ws: Worksheet, run: QCRun, cfg: Config) -> None:
    _write_header_row(ws, _SLOT_ANALYSIS_HEADERS)

    row_idx = 2
    for r in run.rows:
        for column_letter, cr in r.per_column.items():
            for sv in cr.slot_values:
                display_value = _mask_value(sv.raw) if cfg.security.redact_in_reports else sv.raw
                ws.cell(row=row_idx, column=1, value=r.s_no)
                ws.cell(row=row_idx, column=2, value=r.plaza_name)
                ws.cell(row=row_idx, column=3, value=column_letter)
                ws.cell(row=row_idx, column=4, value=cr.field_name)
                ws.cell(row=row_idx, column=5, value=sv.slot)
                ws.cell(row=row_idx, column=6, value=display_value)
                ws.cell(row=row_idx, column=7, value="VALID" if sv.verdict.is_valid else "INVALID")
                ws.cell(row=row_idx, column=8, value=sv.verdict.reason)
                row_idx += 1

    _finalize_sheet(ws, len(_SLOT_ANALYSIS_HEADERS), row_idx - 2, cfg)


def _write_consistency_findings_sheet(ws: Worksheet, run: QCRun, cfg: Config) -> None:
    _write_header_row(ws, _CONSISTENCY_HEADERS)

    entries: list[tuple[RowResult, object]] = [
        (r, finding) for r in run.rows for finding in r.consistency_findings
    ]
    entries.sort(key=lambda pair: STATUS_SEVERITY[pair[1].severity], reverse=True)

    for row_idx, (r, finding) in enumerate(entries, start=2):
        ws.cell(row=row_idx, column=1, value=r.s_no)
        ws.cell(row=row_idx, column=2, value=r.plaza_name)
        ws.cell(row=row_idx, column=3, value=finding.column or "")
        ws.cell(row=row_idx, column=4, value=finding.kind)
        ws.cell(row=row_idx, column=5, value=finding.severity.value)
        ws.cell(row=row_idx, column=6, value=finding.message)

        _apply_status_style(ws, row_idx, len(_CONSISTENCY_HEADERS), finding.severity)

    _finalize_sheet(ws, len(_CONSISTENCY_HEADERS), len(entries), cfg)


def generate_report(run: QCRun, output_path: str, cfg: Config) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    _write_summary_sheet(wb.create_sheet("Summary"), run)
    _write_row_analysis_sheet(wb.create_sheet("Row Analysis"), run, cfg)
    _write_cell_analysis_sheet(wb.create_sheet("Cell Analysis"), run, cfg)
    _write_slot_analysis_sheet(wb.create_sheet("Slot Analysis"), run, cfg)
    _write_consistency_findings_sheet(wb.create_sheet("Consistency Findings"), run, cfg)

    output_dir = Path(output_path).parent
    if output_dir and not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)

    wb.save(output_path)
