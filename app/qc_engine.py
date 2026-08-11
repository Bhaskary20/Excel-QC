"""End-to-end orchestration and workbook-level aggregation, per
BUILD_PLAN.md v2 Section 7 Phase G. Cell-level (Section 5.1) and row-level
(Section 5.2) status rules already live in consistency_checker.py (Phase
F); this module adds Section 5.3 (workbook-level totals) and ties
everything together: read both files -> match rows -> check each row ->
aggregate -> QCRun.
"""

from __future__ import annotations

from typing import Optional

from app.config import Config
from app.consistency_checker import check_row
from app.excel_reader import CellRecord, read_cells
from app.models import QCRun, RowResult, SheetSummary, Status, WorkbookSummary
from app.response_parser import build_row_index
from app.row_matcher import RowMatch, match_rows, resolve_sheet
from app.template_spec import FIRST_DATA_ROW, SHEET_NAME

_ROW_STATUS_FIELD: dict[Status, str] = {
    Status.COMPLETE: "complete_rows",
    Status.PARTIAL: "partial_rows",
    Status.MISSING: "missing_rows",
    Status.INVALID: "invalid_rows",
    Status.REVIEW: "review_rows",
    Status.NOT_APPLICABLE: "not_applicable_rows",
}

_CELL_STATUS_FIELD: dict[Status, str] = {
    Status.COMPLETE: "complete_cells",
    Status.PARTIAL: "partial_cells",
    Status.MISSING: "missing_cells",
    Status.INVALID: "invalid_cells",
    Status.REVIEW: "review_cells",
    Status.NOT_APPLICABLE: "not_applicable_cells",
}


def _build_workbook_summary(rows: list[RowResult]) -> WorkbookSummary:
    summary = WorkbookSummary(total_rows=len(rows))
    total_expected = 0
    total_valid = 0

    for row in rows:
        row_field = _ROW_STATUS_FIELD[row.status]
        setattr(summary, row_field, getattr(summary, row_field) + 1)
        summary.total_consistency_findings += len(row.consistency_findings)

        for cell in row.per_column.values():
            summary.total_cells_checked += 1
            # NOT_APPLICABLE means "doesn't count either way" -- an optional
            # field left blank, or an explicit client N/A, must not drag
            # completeness down just because expected_count was already
            # computed before the NA/optional check ran.
            if cell.expected_count is not None and cell.status != Status.NOT_APPLICABLE:
                total_expected += cell.expected_count
                total_valid += cell.valid_count
            summary.total_missing_slots += cell.missing_count or 0
            summary.total_invalid_slots += cell.invalid_count

            cell_field = _CELL_STATUS_FIELD[cell.status]
            setattr(summary, cell_field, getattr(summary, cell_field) + 1)

    summary.total_expected_slots = total_expected
    summary.total_valid_slots = total_valid
    summary.overall_completeness = (total_valid / total_expected) if total_expected > 0 else None
    return summary


def _build_sheet_summary(rows: list[RowResult]) -> SheetSummary:
    summary = SheetSummary(sheet=SHEET_NAME, total_rows=len(rows))
    total_expected = 0
    total_valid = 0

    for row in rows:
        if row.status == Status.COMPLETE:
            summary.complete_rows += 1
        elif row.status == Status.PARTIAL:
            summary.partial_rows += 1

        for cell in row.per_column.values():
            if cell.expected_count is not None and cell.status != Status.NOT_APPLICABLE:
                total_expected += cell.expected_count
                total_valid += cell.valid_count
            summary.missing_slots += cell.missing_count or 0
            summary.invalid_slots += cell.invalid_count

    summary.expected_slots = total_expected
    summary.valid_slots = total_valid
    summary.completeness = (total_valid / total_expected) if total_expected > 0 else None
    return summary


def _find_extra_response_rows(
    response_cells: list[CellRecord], response_sheet: Optional[str], row_matches: list[RowMatch]
) -> list[str]:
    if response_sheet is None:
        return []

    claimed_rows = {m.response_row for m in row_matches if m.response_row is not None}
    rows_with_identity_content: set[int] = set()
    for c in response_cells:
        if (
            c.sheet == response_sheet
            and c.col in (1, 3)  # S.No or Plaza Name
            and c.row >= FIRST_DATA_ROW  # exclude the title/header rows above the data
            and c.text.strip()
        ):
            rows_with_identity_content.add(c.row)

    extras = sorted(r for r in rows_with_identity_content if r not in claimed_rows)
    return [f"{response_sheet}!row {r}" for r in extras]


def run_qc_from_cells(
    template_cells: list[CellRecord],
    response_cells: list[CellRecord],
    cfg: Config,
    template_path: str = "",
    response_path: str = "",
) -> QCRun:
    """Core pipeline, decoupled from file I/O so it's testable with
    synthetic CellRecords. run_qc() below is the file-path entry point."""
    row_matches = match_rows(template_cells, response_cells)

    response_sheet = resolve_sheet(response_cells, SHEET_NAME)
    row_index = build_row_index(response_cells, response_sheet) if response_sheet else {}

    rows = [check_row(row_index, rm, cfg) for rm in row_matches]

    return QCRun(
        template_path=template_path,
        response_path=response_path,
        rows=rows,
        sheet_summary=_build_sheet_summary(rows),
        workbook_summary=_build_workbook_summary(rows),
        extra_response_rows=_find_extra_response_rows(response_cells, response_sheet, row_matches),
    )


def run_qc(template_path: str, response_path: str, cfg: Config) -> QCRun:
    template_cells = read_cells(template_path)
    response_cells = read_cells(response_path)
    return run_qc_from_cells(template_cells, response_cells, cfg, template_path, response_path)
