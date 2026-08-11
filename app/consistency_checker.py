"""Per-row assembly: N from column H, per-column CellResults (with
missing_slots), row-level status/completeness, and cross-column
ConsistencyFindings (J date chain, J window coverage, L duplicate phones).
BUILD_PLAN.md v2 Section 7 Phase F.

Cell-level status (Section 5.1) and row-level status (Section 5.2) are
both mechanical, pure functions of what's already known once a row is
parsed, so they live here. Workbook-level aggregation and end-to-end
orchestration (matching a template to a response file) are qc_engine's
job (Phase G) -- this module only ever processes one already-matched row
at a time.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from app.config import Config
from app.models import CellResult, ConsistencyFinding, RowResult, Status
from app.response_parser import ParsedCell, parse_row_cells
from app.row_matcher import RowMatch
from app.template_spec import CONTRACT_WINDOW, SHEET_NAME, get_column, input_columns, slotted_columns

# Worst-to-best isn't a strict total order in the spec, so this is a
# judgment call: INVALID (actively wrong data) is worse than MISSING
# (nothing offered), which is worse than REVIEW (uncertain), which is
# worse than PARTIAL. COMPLETE and NOT_APPLICABLE both mean "nothing to
# flag here" and share the lowest severity.
STATUS_SEVERITY: dict[Status, int] = {
    Status.COMPLETE: 0,
    Status.NOT_APPLICABLE: 0,
    Status.PARTIAL: 1,
    Status.REVIEW: 2,
    Status.MISSING: 3,
    Status.INVALID: 4,
}

_SLOTTED_NON_ANCHOR = [c.letter for c in slotted_columns() if c.letter != "H"]


def _compute_n(h_parsed: ParsedCell) -> int:
    if h_parsed.is_unfilled_scaffold or h_parsed.is_na:
        return 0
    return len(h_parsed.slot_values)


def _decide_cell(
    expected_count: Optional[int],
    detected: int,
    valid: int,
    is_blank: bool,
    is_na: bool,
    required: bool,
    missing_slots: list[int],
) -> tuple[Status, Optional[float], str]:
    if is_blank:
        if required:
            expected_desc = str(expected_count) if expected_count is not None else "unknown"
            return Status.MISSING, 0.0, f"no response provided; expected {expected_desc}"
        return Status.NOT_APPLICABLE, None, "optional field left blank"

    if is_na:
        return Status.NOT_APPLICABLE, None, "marked not applicable"

    if detected > 0 and valid == 0:
        return Status.INVALID, 0.0, f"{detected} values provided, none valid"

    if expected_count is None:
        return Status.REVIEW, None, f"expected count unknown; {valid} valid of {detected} provided"

    if valid >= expected_count:
        return Status.COMPLETE, 1.0, f"all {expected_count} expected values valid"

    if 0 < valid < expected_count:
        missing_desc = ", ".join(str(s) for s in missing_slots) if missing_slots else "none"
        return (
            Status.PARTIAL,
            valid / expected_count,
            f"{valid} valid of {expected_count} expected; missing slots: {missing_desc}",
        )

    return Status.REVIEW, None, "unhandled combination"


def _build_cell_result(column_letter: str, response_row: Optional[int], parsed: ParsedCell, n: int) -> CellResult:
    spec = get_column(column_letter)

    if spec.slotted:
        expected_count = n if n > 0 else None
        n_forces_blank = n == 0
    else:
        expected_count = 1
        n_forces_blank = False

    detected = len(parsed.slot_values)
    valid = sum(1 for sv in parsed.slot_values if sv.verdict.is_valid)
    invalid = detected - valid

    present_slots = {sv.slot for sv in parsed.slot_values}
    missing_slots = (
        [s for s in range(1, expected_count + 1) if s not in present_slots] if expected_count else []
    )

    is_blank = parsed.is_unfilled_scaffold or n_forces_blank
    status, completeness, reason = _decide_cell(
        expected_count=expected_count,
        detected=detected,
        valid=valid,
        is_blank=is_blank,
        is_na=parsed.is_na,
        required=spec.required,
        missing_slots=missing_slots,
    )

    if parsed.note:
        reason = f"{reason}; {parsed.note}" if reason else parsed.note

    missing_count = max(expected_count - valid, 0) if expected_count is not None else None
    cell_addr = f"{column_letter}{response_row}" if response_row is not None else ""

    return CellResult(
        sheet=SHEET_NAME,
        cell=cell_addr,
        column=column_letter,
        field_name=spec.header,
        value_type=spec.value_type,
        expected_count=expected_count,
        detected_count=detected,
        valid_count=valid,
        invalid_count=invalid,
        missing_count=missing_count,
        missing_slots=missing_slots,
        completeness=completeness,
        status=status,
        confidence=1.0,  # row-match-strategy confidence is layered on by qc_engine (Phase G)
        reason=reason,
        slot_values=parsed.slot_values,
    )


def _parse_date_pair(normalized: str) -> tuple[date, date]:
    start_str, end_str = normalized.split("/")
    return date.fromisoformat(start_str), date.fromisoformat(end_str)


def _check_date_chain(j_result: CellResult) -> list[ConsistencyFinding]:
    ranges = [
        (sv.slot, *_parse_date_pair(sv.verdict.normalized))
        for sv in j_result.slot_values
        if sv.verdict.is_valid and sv.verdict.normalized
    ]
    if len(ranges) < 2:
        return []

    ranges.sort(key=lambda r: r[1])  # order by start date
    findings: list[ConsistencyFinding] = []
    for (slot_a, _, end_a), (slot_b, start_b, _) in zip(ranges, ranges[1:]):
        gap_days = (start_b - end_a).days
        if abs(gap_days) > 1:
            findings.append(
                ConsistencyFinding(
                    kind="date_chain_gap" if gap_days > 0 else "date_chain_overlap",
                    column="J",
                    severity=Status.REVIEW,
                    message=(
                        f"contract chain: {abs(gap_days)} day "
                        f"{'gap' if gap_days > 0 else 'overlap'} between slot {slot_a} "
                        f"(ends {end_a.isoformat()}) and slot {slot_b} (starts {start_b.isoformat()})"
                    ),
                )
            )
    return findings


def _check_window_coverage(j_result: CellResult) -> list[ConsistencyFinding]:
    ranges = [
        _parse_date_pair(sv.verdict.normalized)
        for sv in j_result.slot_values
        if sv.verdict.is_valid and sv.verdict.normalized
    ]
    if not ranges:
        return []

    window_start, window_end = CONTRACT_WINDOW
    earliest_start = min(r[0] for r in ranges)
    latest_end = max(r[1] for r in ranges)

    findings: list[ConsistencyFinding] = []
    if earliest_start > window_start:
        findings.append(
            ConsistencyFinding(
                kind="date_window_coverage", column="J", severity=Status.REVIEW,
                message=f"contract coverage starts {earliest_start.isoformat()}, expected from {window_start.isoformat()}",
            )
        )
    if latest_end < window_end:
        findings.append(
            ConsistencyFinding(
                kind="date_window_coverage", column="J", severity=Status.REVIEW,
                message=f"contract coverage ends {latest_end.isoformat()}, expected through {window_end.isoformat()}",
            )
        )
    return findings


def _check_duplicate_phones(l_result: CellResult) -> list[ConsistencyFinding]:
    valid_values = [sv.verdict.normalized for sv in l_result.slot_values if sv.verdict.is_valid and sv.verdict.normalized]
    if len(valid_values) >= 2 and len(set(valid_values)) == 1:
        return [
            ConsistencyFinding(
                kind="duplicate_phone", column="L", severity=Status.REVIEW,
                message=f"same phone number used for all {len(valid_values)} agencies",
            )
        ]
    return []


def _check_consistency(per_column: dict[str, CellResult], n: int) -> list[ConsistencyFinding]:
    findings: list[ConsistencyFinding] = []

    if n > 0:
        for letter in _SLOTTED_NON_ANCHOR:
            cell = per_column[letter]
            if cell.missing_slots:
                slots_desc = ", ".join(str(s) for s in cell.missing_slots)
                findings.append(
                    ConsistencyFinding(
                        kind="slot_count_mismatch", column=letter, severity=Status.REVIEW,
                        message=f"{n} agencies declared; {cell.field_name} missing at slot(s) {slots_desc}",
                    )
                )

    findings.extend(_check_date_chain(per_column["J"]))
    findings.extend(_check_window_coverage(per_column["J"]))
    findings.extend(_check_duplicate_phones(per_column["L"]))

    return findings


def _row_status(
    per_column: dict[str, CellResult], identity_mismatches: list[str], findings: list[ConsistencyFinding]
) -> Status:
    candidates = [max(per_column.values(), key=lambda r: STATUS_SEVERITY[r.status]).status]
    if identity_mismatches:
        candidates.append(Status.REVIEW)
    if findings:
        candidates.append(max((f.severity for f in findings), key=lambda s: STATUS_SEVERITY[s]))
    return max(candidates, key=lambda s: STATUS_SEVERITY[s])


def _row_completeness(per_column: dict[str, CellResult], n: int) -> Optional[float]:
    if n <= 0:
        return None
    slotted_letters = [c.letter for c in slotted_columns()]
    total_valid = sum(per_column[letter].valid_count for letter in slotted_letters)
    denominator = n * len(slotted_letters)
    return total_valid / denominator if denominator > 0 else None


def check_row(row_index: dict[tuple[int, int], object], row_match: RowMatch, cfg: Config) -> RowResult:
    parsed_cells = parse_row_cells(row_index, row_match.response_row, cfg)
    n = _compute_n(parsed_cells["H"])

    per_column: dict[str, CellResult] = {
        spec.letter: _build_cell_result(spec.letter, row_match.response_row, parsed_cells[spec.letter], n)
        for spec in input_columns()
    }

    findings = _check_consistency(per_column, n)
    status = _row_status(per_column, row_match.identity_mismatches, findings)
    completeness = _row_completeness(per_column, n)

    return RowResult(
        sheet=SHEET_NAME,
        response_row=row_match.response_row,
        s_no=row_match.template_s_no,
        plaza_code=row_match.template_plaza_code,
        plaza_name=row_match.template_plaza_name,
        ro=row_match.template_ro,
        piu=row_match.template_piu,
        match_strategy=row_match.match_strategy,
        n_contracts=n,
        per_column=per_column,
        consistency_findings=findings,
        status=status,
        completeness=completeness,
        identity_mismatches=row_match.identity_mismatches,
    )
