"""Per-row assembly: N from column H, per-column CellResults (with
missing_slots), row-level status/completeness, and the one remaining
cross-column ConsistencyFinding (slot count vs. declared agency count).
BUILD_PLAN.md v2 Section 7 Phase F.

Cell-level status (Section 5.1) and row-level status (Section 5.2) are
both mechanical, pure functions of what's already known once a row is
parsed, so they live here. Workbook-level aggregation and end-to-end
orchestration (matching a template to a response file) are qc_engine's
job (Phase G) -- this module only ever processes one already-matched row
at a time.
"""

from __future__ import annotations

import re
from typing import Optional

from app.config import Config
from app.excel_reader import CellRecord
from app.models import CellResult, ConsistencyFinding, RowResult, Status
from app.response_parser import ParsedCell, parse_row_cells
from app.row_matcher import RowMatch
from app.template_spec import SHEET_NAME, get_column, input_columns, slotted_columns

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

# AE/IE (Supervision Consultant, Team Leader) and HTMS/Toll Expert don't
# necessarily have one real answer per declared agency -- a single
# consultant can legitimately span several agency-contract periods for the
# same plaza. Comparing their slot count against the agency count (like
# every other slotted column) produced false "partial" verdicts. These
# three are graded as a group instead (see aeie_htms_group_status), not
# folded into the per-agency quantity check the remaining slotted columns
# still use. Exported (no leading underscore) because report_generator
# also needs it, to keep the Status sheet's remark in sync with what
# actually drives the row status instead of re-deriving its own notion of
# "AE/IE/HTMS has a problem".
AEIE_HTMS_COLUMNS = ("N", "O", "P")
_QUANTITY_CHECKED_COLUMNS = [c for c in _SLOTTED_NON_ANCHOR if c not in AEIE_HTMS_COLUMNS]


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


def _check_consistency(per_column: dict[str, CellResult], n: int) -> list[ConsistencyFinding]:
    """Only the quantity check remains: does each of the 8 core columns
    (_QUANTITY_CHECKED_COLUMNS) have as many valid entries as agencies
    declared. Date-chain gap/overlap, date-window coverage, and
    duplicate-phone were deliberately removed at the user's request --
    kept the tool simple rather than layering on cross-column judgment
    calls beyond "does the count match".
    """
    findings: list[ConsistencyFinding] = []

    if n > 0:
        for letter in _QUANTITY_CHECKED_COLUMNS:
            cell = per_column[letter]
            # NOT_APPLICABLE means the client explicitly said this column
            # doesn't apply -- that's not the same finding as "forgot to
            # fill some slots in", even though missing_slots is populated
            # either way (parse_cell leaves slot_values empty for an NA cell).
            if cell.missing_slots and cell.status != Status.NOT_APPLICABLE:
                slots_desc = ", ".join(str(s) for s in cell.missing_slots)
                findings.append(
                    ConsistencyFinding(
                        kind="slot_count_mismatch", column=letter, severity=Status.REVIEW,
                        message=f"{n} agencies declared; {cell.field_name} missing at slot(s) {slots_desc}",
                    )
                )

    return findings


def aeie_htms_group_status(per_column: dict[str, CellResult]) -> Status:
    """Group verdict for N/O/P (see AEIE_HTMS_COLUMNS): "has real data"
    means at least one valid value, not necessarily as many as there are
    agencies. All three answered -> COMPLETE. Some but not all -> PARTIAL.
    All three are blank/NA -> MISSING (incomplete data), same wording as
    the rest of the tool's "no free passes on a non-answer" rule.
    """
    answered = sum(1 for c in AEIE_HTMS_COLUMNS if per_column[c].valid_count > 0)
    if answered == len(AEIE_HTMS_COLUMNS):
        return Status.COMPLETE
    if answered == 0:
        return Status.MISSING
    return Status.PARTIAL


def _row_status(
    per_column: dict[str, CellResult], identity_mismatches: list[str], findings: list[ConsistencyFinding]
) -> Status:
    core_columns = [cell for letter, cell in per_column.items() if letter not in AEIE_HTMS_COLUMNS]
    candidates = [
        max(core_columns, key=lambda r: STATUS_SEVERITY[r.status]).status,
        aeie_htms_group_status(per_column),
    ]
    if identity_mismatches:
        candidates.append(Status.REVIEW)
    if findings:
        candidates.append(max((f.severity for f in findings), key=lambda s: STATUS_SEVERITY[s]))
    return max(candidates, key=lambda s: STATUS_SEVERITY[s])


def _row_completeness(per_column: dict[str, CellResult], n: int) -> Optional[float]:
    if n <= 0:
        return None
    slotted_letters = [c.letter for c in slotted_columns()]
    # Cap each column's contribution at n: a client who supplies more phone
    # numbers than declared agencies has that column at 100%, not >100% --
    # oversupply on one column must not inflate the row's overall figure.
    total_valid = sum(min(per_column[letter].valid_count, n) for letter in slotted_letters)
    denominator = n * len(slotted_letters)
    return total_valid / denominator if denominator > 0 else None


_MERGE_ANCHOR_ROW = re.compile(r"(\d+)$")


def _find_merged_with_rows(row_index: dict[tuple[int, int], CellRecord], response_row: Optional[int]) -> tuple[int, ...]:
    """Other response-workbook row numbers this row's INPUT columns are
    merged-cell-linked to -- e.g. two adjoining toll plazas where the PIU
    filled in agency/contract/manager details once, in an Excel merge
    spanning both rows, rather than repeating the same answer twice.
    """
    if response_row is None:
        return ()

    other_rows: set[int] = set()
    for spec in input_columns():
        record = row_index.get((response_row, spec.index))
        if record is None or not record.is_merged or record.merge_anchor is None:
            continue
        match = _MERGE_ANCHOR_ROW.search(record.merge_anchor)
        if not match:
            continue
        anchor_row = int(match.group(1))
        if anchor_row != response_row:
            other_rows.add(anchor_row)

    return tuple(sorted(other_rows))


def check_row(row_index: dict[tuple[int, int], CellRecord], row_match: RowMatch, cfg: Config) -> RowResult:
    parsed_cells = parse_row_cells(row_index, row_match.response_row, cfg)
    n = _compute_n(parsed_cells["H"])

    per_column: dict[str, CellResult] = {
        spec.letter: _build_cell_result(spec.letter, row_match.response_row, parsed_cells[spec.letter], n)
        for spec in input_columns()
    }

    findings = _check_consistency(per_column, n)
    status = _row_status(per_column, row_match.identity_mismatches, findings)
    completeness = _row_completeness(per_column, n)
    merged_with_rows = _find_merged_with_rows(row_index, row_match.response_row)

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
        merged_with_rows=merged_with_rows,
        identity_mismatches=row_match.identity_mismatches,
    )
