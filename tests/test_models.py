"""Phase B gate: the slot-aware domain model imports cleanly, and
VALIDATOR_REGISTRY has an entry for every template_spec.ValueType.

Per-type validation behavior is exercised by test_validators.py once that
module is rewritten (Phase D). This file only checks the shape of the
model and the registry.
"""

from app.config import load_config
from app.models import (
    VALIDATOR_REGISTRY,
    CellResult,
    ConsistencyFinding,
    QCRun,
    RowResult,
    SheetSummary,
    SlotValue,
    Status,
    ValueVerdict,
    WorkbookSummary,
    get_validator,
)
from app.template_spec import SHEET_NAME, ValueType, get_column


def test_every_value_type_has_a_registry_entry():
    missing = [t for t in ValueType if t not in VALIDATOR_REGISTRY]
    assert not missing, f"ValueType members missing from VALIDATOR_REGISTRY: {missing}"


def test_get_validator_resolves_every_type():
    for value_type in ValueType:
        assert callable(get_validator(value_type))


def test_registered_validator_accepts_nonempty_rejects_blank():
    # Whatever's currently registered for PHONE (placeholder pre-Phase D,
    # real validator after) must agree on these two unambiguous cases.
    cfg = load_config()
    validator = get_validator(ValueType.PHONE)
    spec = get_column("L")  # Contact of Toll Manager -- the real PHONE column

    ok = validator("9876543210", cfg, spec)
    assert ok.is_valid is True

    blank = validator("   ", cfg, spec)
    assert blank.is_valid is False


def test_status_members_match_spec():
    names = {s.value for s in Status}
    assert names == {"COMPLETE", "PARTIAL", "MISSING", "INVALID", "REVIEW", "NOT_APPLICABLE"}


def test_slot_value_holds_a_verdict():
    sv = SlotValue(slot=1, raw="9876543210", verdict=ValueVerdict(is_valid=True, normalized="9876543210"))
    assert sv.verdict.is_valid
    assert sv.slot == 1


def test_cell_result_tracks_missing_slots_explicitly():
    result = CellResult(
        sheet=SHEET_NAME, cell="L15", column="L", field_name="Contact of Toll Manager",
        value_type=ValueType.PHONE, expected_count=4, detected_count=2, valid_count=2,
        invalid_count=0, missing_count=2, missing_slots=[3, 4], completeness=0.5,
        status=Status.PARTIAL, confidence=1.0, reason="2 valid of 4 expected; slots 3, 4 missing",
        slot_values=[
            SlotValue(slot=1, raw="9876543210", verdict=ValueVerdict(is_valid=True, normalized="9876543210")),
            SlotValue(slot=2, raw="9876543211", verdict=ValueVerdict(is_valid=True, normalized="9876543211")),
        ],
    )
    assert result.missing_slots == [3, 4]
    assert len(result.slot_values) == 2


def test_row_result_holds_per_column_cell_results_and_findings():
    cell = CellResult(
        sheet=SHEET_NAME, cell="H15", column="H", field_name="Agency name",
        value_type=ValueType.TEXT, expected_count=None, detected_count=4, valid_count=4,
        invalid_count=0, missing_count=0, missing_slots=[], completeness=1.0,
        status=Status.COMPLETE, confidence=1.0, reason="all agencies named", slot_values=[],
    )
    finding = ConsistencyFinding(
        kind="slot_count_mismatch", column="L", severity=Status.REVIEW,
        message="4 agencies declared but only 2 phone numbers provided",
    )
    row = RowResult(
        sheet=SHEET_NAME, response_row=15, s_no=13, plaza_code="345061", plaza_name="SEHATGANJ",
        ro="Bhopal", piu="Bhopal", match_strategy="s_no", n_contracts=4,
        per_column={"H": cell}, consistency_findings=[finding],
        status=Status.PARTIAL, completeness=0.5,
    )
    assert row.n_contracts == 4
    assert row.per_column["H"].status == Status.COMPLETE
    assert row.consistency_findings[0].kind == "slot_count_mismatch"


def test_qc_run_defaults_are_empty_and_well_formed():
    run = QCRun(template_path="template/Format.xlsx", response_path="response.xlsx")
    assert run.rows == []
    assert run.extra_response_rows == []
    assert isinstance(run.sheet_summary, SheetSummary)
    assert run.sheet_summary.sheet == SHEET_NAME
    assert isinstance(run.workbook_summary, WorkbookSummary)
    assert run.workbook_summary.total_rows == 0
