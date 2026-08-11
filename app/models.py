"""Slot-aware domain model (v2), built against template_spec.py.

Status and ValueVerdict carry over from v1 unchanged -- they're generic
enough that the switch to a fixed, slot-based template doesn't touch them.
Everything else is new: v1's FieldType/TypeProfile/TYPE_REGISTRY existed to
support *inferring* a field's type and expected count from an unknown
template: with template_spec.py declaring both directly, that inference
apparatus is gone. What replaces it is VALIDATOR_REGISTRY, a much smaller
mapping of template_spec.ValueType -> validator function.

Three levels of result, matching BUILD_PLAN.md v2 Section 5:
  SlotValue  -- one parsed value at one numbered slot in one cell
  CellResult -- one (row, column) pair: N expected slots vs what was found
  RowResult  -- one plaza: all 14 input columns plus cross-column findings
QCRun aggregates every RowResult plus workbook-level totals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

from app.config import Config
from app.template_spec import SHEET_NAME, ValueType


class Status(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    INVALID = "INVALID"
    REVIEW = "REVIEW"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class ValueVerdict:
    """Result of validating a single parsed value."""

    is_valid: bool
    normalized: Optional[str]  # canonical form, e.g. "9876543210" for "+91 98765 43210"
    reason: str = ""  # shape description only, e.g. "expected 10 digits, got 4"
    # NEVER put the raw client value in `reason` -- it lands directly in QC_Report.xlsx.


def _validator_not_implemented(value: str, cfg: "Config") -> ValueVerdict:
    text = value.strip()
    if text:
        return ValueVerdict(is_valid=True, normalized=text, reason="")
    return ValueVerdict(is_valid=False, normalized=None, reason="empty value")


VALIDATOR_REGISTRY: dict[ValueType, Callable[[str, "Config"], ValueVerdict]] = {
    value_type: _validator_not_implemented for value_type in ValueType
}


def get_validator(value_type: ValueType) -> Callable[[str, "Config"], ValueVerdict]:
    return VALIDATOR_REGISTRY[value_type]


# ============================================================================
# Slot / cell / row results
# ============================================================================


@dataclass(frozen=True)
class SlotValue:
    slot: int  # 1-based slot number as parsed -- not necessarily contiguous
    raw: str
    verdict: ValueVerdict


@dataclass(frozen=True)
class CellResult:
    """One (row, column) pair -- e.g. plaza SEHATGANJ's 'Contact of Toll
    Manager' column. For slotted columns, expected_count is the row's N
    (agency count, from column H); for the anchor column H itself and for
    non-slotted single-value columns, expected_count is 1 or None as
    appropriate -- see qc_engine.py (Phase G) for exactly how N propagates.
    """

    sheet: str
    cell: str  # response cell address, e.g. "H15"
    column: str  # letter, e.g. "H"
    field_name: str  # ColumnSpec.header
    value_type: ValueType
    expected_count: Optional[int]
    detected_count: int
    valid_count: int
    invalid_count: int
    missing_count: Optional[int]
    missing_slots: list[int]  # which slot numbers (1..N) had nothing there
    completeness: Optional[float]
    status: Status
    confidence: float
    reason: str
    slot_values: list[SlotValue] = field(default_factory=list)


@dataclass(frozen=True)
class ConsistencyFinding:
    """A cross-column or cross-slot problem within one row -- e.g. a date
    chain gap between contract slots, or fewer phone numbers than agencies."""

    kind: str  # "slot_count_mismatch" | "date_chain_gap" | "date_window_coverage" | "duplicate_phone" | ...
    column: Optional[str]  # letter, if the finding is column-specific
    severity: Status  # REVIEW or INVALID
    message: str


@dataclass(frozen=True)
class RowResult:
    """One plaza. per_column covers the 14 INPUT columns (F, G, H..R, S);
    KEY columns (A-E) are never graded, only checked for identity drift."""

    sheet: str
    response_row: Optional[int]  # actual row number in the response workbook; None if unmatched
    s_no: int
    plaza_code: str
    plaza_name: str
    ro: str
    piu: str
    match_strategy: str  # "s_no" | "plaza_name" | "position" | "unmatched"
    n_contracts: int
    per_column: dict[str, CellResult]
    consistency_findings: list[ConsistencyFinding]
    status: Status
    completeness: Optional[float]
    identity_mismatches: list[str] = field(default_factory=list)


# ============================================================================
# Rollups
# ============================================================================


@dataclass
class SheetSummary:
    sheet: str
    total_rows: int = 0
    expected_slots: int = 0
    valid_slots: int = 0
    missing_slots: int = 0
    invalid_slots: int = 0
    complete_rows: int = 0
    partial_rows: int = 0
    completeness: Optional[float] = None


@dataclass
class WorkbookSummary:
    total_rows: int = 0
    total_cells_checked: int = 0  # rows x graded (INPUT) columns
    total_expected_slots: int = 0
    total_valid_slots: int = 0
    total_missing_slots: int = 0
    total_invalid_slots: int = 0
    complete_cells: int = 0
    partial_cells: int = 0
    missing_cells: int = 0
    invalid_cells: int = 0
    review_cells: int = 0
    not_applicable_cells: int = 0
    complete_rows: int = 0
    partial_rows: int = 0
    missing_rows: int = 0
    review_rows: int = 0
    overall_completeness: Optional[float] = None
    total_consistency_findings: int = 0


@dataclass
class QCRun:
    template_path: str
    response_path: str
    generated_at: datetime = field(default_factory=datetime.now)
    engine_version: str = "0.2.0"
    rows: list[RowResult] = field(default_factory=list)
    sheet_summary: SheetSummary = field(default_factory=lambda: SheetSummary(sheet=SHEET_NAME))
    workbook_summary: WorkbookSummary = field(default_factory=WorkbookSummary)
    extra_response_rows: list[str] = field(default_factory=list)  # plaza rows in the response with no template match
