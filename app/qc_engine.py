"""Orchestrator: FieldSpec + response cells -> QCRun. Home of the status
decision table (BUILD_PLAN.md Phase 10) -- the single most consequential
piece of logic in the project.

decide_status() is the table itself: a pure function of (E, D, V, I, spec,
cfg) plus two booleans the table's own rows 1-2 need but can't derive from
counts alone (cell_found, is_marked_na -- a cell holding exactly one N/A
value has the same D=1/V=1 signature as a genuine single valid answer, so
the caller must say which one it is).

Confidence is a separate concern layered on top by evaluate_field(), not
part of the table: it's min(field_type_confidence, expected.confidence),
discounted further when the field matcher had to fall back to a weaker
pairing strategy (row_offset/label_match/sheet_index). When that combined
confidence drops below cfg.status.low_confidence_review_threshold, the
status is upgraded to REVIEW (MISSING is left alone -- a blank is a blank
regardless of how sure we are about anything else).

run_qc_from_specs() works from an already-built spec list, so it's fully
usable before template_analyzer.py (Phase 7) exists. run_qc() is the
file-path entry point the plan specifies; it lazy-imports template_analyzer
so this module stays importable even though that one doesn't exist yet.
"""

from __future__ import annotations

from typing import Optional

from app.config import Config
from app.excel_reader import CellRecord, read_cells
from app.field_matcher import FieldMatch, match_fields
from app.models import (
    FieldSpec,
    ParsedValue,
    QCResult,
    QCRun,
    SheetSummary,
    Status,
    WorkbookSummary,
)
from app.response_parser import parse_response
from app.value_splitter import NA_SENTINEL

_FALLBACK_STRATEGY_PENALTY = {
    "exact_coordinate": 1.0,
    "sheet_name_normalized": 1.0,
    "sheet_index": 0.85,
    "row_offset": 0.8,
    "label_match": 0.8,
    "unmatched": 1.0,  # irrelevant: cell_found=False short-circuits at row 1 before confidence matters
}


def decide_status(
    E: Optional[int],
    D: int,
    V: int,
    I: int,
    spec: FieldSpec,
    cfg: Config,
    cell_found: bool = True,
    is_marked_na: bool = False,
) -> tuple[Status, Optional[float], str]:
    """The 12-row table, evaluated top to bottom -- first match wins."""
    bound = spec.expected.bound

    # 1. Response cell not found
    if not cell_found:
        return Status.MISSING, 0.0, "field not present in response workbook"

    # 2. Only value is the NA sentinel
    if is_marked_na:
        return Status.NOT_APPLICABLE, None, "client marked not applicable"

    # 3 / 4. Nothing provided
    if D == 0:
        if spec.required:
            expected_desc = str(E) if E is not None else "unknown"
            return Status.MISSING, 0.0, f"no response provided; expected {expected_desc}"
        fallback_status = Status[cfg.status.treat_blank_optional_as]
        return fallback_status, 0.0, "optional field left blank"

    # 5 / 6. Expected count unknown
    if E is None:
        if V == 0:
            return Status.INVALID, None, f"{D} values provided, none valid"
        return Status.REVIEW, None, f"expected count unknown; {V} valid of {D} provided"

    # 7. Everything provided is invalid
    if V == 0:
        return Status.INVALID, 0.0, f"{D} values provided, none valid for type {spec.field_type.value}"

    # 8. Max-bound fields ("up to N") are complete once satisfied, not overshot
    if bound == "max" and V <= E and V > 0:
        completeness = min(V / E, 1.0) if E > 0 else None
        return Status.COMPLETE, completeness, f"within maximum of {E}"

    # 9 / 10. Requirement met or exceeded
    if V >= E:
        if D > E and cfg.status.oversupply_is_review:
            return Status.REVIEW, 1.0, f"{D} values provided, {E} expected"
        return Status.COMPLETE, 1.0, f"all {E} expected values valid"

    # 11. Partially satisfied
    if 0 < V < E:
        M = max(E - V, 0)
        completeness = V / E if E > 0 else None
        return Status.PARTIAL, completeness, f"{V} valid of {E} expected; {M} missing"

    # 12. Defensive fallback -- rows 1-11 are exhaustive for any sane (E, D, V, I)
    # with D >= V + I, V >= 0; this only fires if that invariant is somehow broken.
    return Status.REVIEW, None, "unhandled combination"


def _compute_match_confidence(spec: FieldSpec, match_strategy: str) -> float:
    base = min(spec.field_type_confidence, spec.expected.confidence)
    return base * _FALLBACK_STRATEGY_PENALTY.get(match_strategy, 1.0)


def evaluate_field(match: FieldMatch, cfg: Config) -> QCResult:
    spec = match.spec
    cell_found = match.cell is not None

    values: list[ParsedValue] = []
    note = ""
    if cell_found:
        values, note = parse_response(spec, match.cell, cfg)

    is_marked_na = len(values) == 1 and values[0].raw == NA_SENTINEL
    D = 0 if is_marked_na else len(values)
    V = 0 if is_marked_na else sum(1 for v in values if v.verdict.is_valid)
    I = 0 if is_marked_na else sum(1 for v in values if not v.verdict.is_valid)
    E = spec.expected.count

    status, completeness, reason = decide_status(
        E, D, V, I, spec, cfg, cell_found=cell_found, is_marked_na=is_marked_na
    )

    if note:
        reason = f"{reason}; {note}" if reason else note

    confidence = _compute_match_confidence(spec, match.strategy)
    if status != Status.MISSING and confidence < cfg.status.low_confidence_review_threshold:
        status = Status.REVIEW
        reason = f"{reason} (low confidence: {confidence:.2f})"

    missing_count = max(E - V, 0) if E is not None else None

    return QCResult(
        sheet=spec.sheet,
        cell=spec.cell,
        field_name=spec.field_name,
        field_type=spec.field_type,
        expected_count=E,
        detected_count=D,
        valid_count=V,
        invalid_count=I,
        missing_count=missing_count,
        completeness=completeness,
        status=status,
        confidence=confidence,
        reason=reason,
        values=values,
    )


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _build_sheet_summary(sheet: str, results: list[QCResult]) -> SheetSummary:
    summary = SheetSummary(sheet=sheet)
    total_e = 0
    total_v = 0

    for r in results:
        if r.expected_count is not None:
            total_e += r.expected_count
            total_v += r.valid_count
        summary.missing += r.missing_count or 0
        summary.invalid += r.invalid_count
        if r.status == Status.COMPLETE:
            summary.complete_cells += 1
        elif r.status == Status.PARTIAL:
            summary.partial_cells += 1

    summary.expected_responses = total_e
    summary.valid_responses = total_v
    summary.completeness = (total_v / total_e) if total_e > 0 else None
    return summary


_STATUS_TO_SUMMARY_FIELD = {
    Status.COMPLETE: "complete_cells",
    Status.PARTIAL: "partial_cells",
    Status.MISSING: "missing_cells",
    Status.INVALID: "invalid_cells",
    Status.REVIEW: "review_cells",
    Status.NOT_APPLICABLE: "not_applicable_cells",
}


def _build_workbook_summary(results: list[QCResult], sheet_count: int) -> WorkbookSummary:
    summary = WorkbookSummary(total_sheets=sheet_count, total_cells_checked=len(results))
    total_e = 0
    total_v = 0

    for r in results:
        if r.expected_count is not None:
            total_e += r.expected_count
            total_v += r.valid_count
        summary.total_missing += r.missing_count or 0
        summary.total_invalid += r.invalid_count

        field_name = _STATUS_TO_SUMMARY_FIELD[r.status]
        setattr(summary, field_name, getattr(summary, field_name) + 1)

    summary.total_expected = total_e
    summary.total_valid = total_v
    summary.overall_completeness = (total_v / total_e) if total_e > 0 else None
    return summary


def run_qc_from_specs(
    specs: list[FieldSpec],
    response_cells: list[CellRecord],
    cfg: Config,
    template_path: str = "",
    response_path: str = "",
) -> QCRun:
    matches, extra_cells = match_fields(specs, response_cells, cfg)
    results = [evaluate_field(m, cfg) for m in matches]

    sheets = _ordered_unique([s.sheet for s in specs])
    sheet_summaries = [_build_sheet_summary(sheet, [r for r in results if r.sheet == sheet]) for sheet in sheets]
    workbook_summary = _build_workbook_summary(results, len(sheets))

    return QCRun(
        template_path=template_path,
        response_path=response_path,
        ai_enabled=cfg.ai.enabled,
        results=results,
        sheet_summaries=sheet_summaries,
        workbook_summary=workbook_summary,
        extra_response_cells=extra_cells,
    )


def run_qc(template_path: str, response_path: str, cfg: Config) -> QCRun:
    """CLI entry point per BUILD_PLAN.md Phase 10. Needs template_analyzer.py
    (Phase 7), which is blocked pending the real template -- imported here,
    not at module load, so the rest of this module stays usable meanwhile."""
    from app.template_analyzer import analyze_template

    specs = analyze_template(template_path, cfg)
    response_cells = read_cells(response_path)
    return run_qc_from_specs(specs, response_cells, cfg, template_path=template_path, response_path=response_path)
