"""Phase F gate (consistency_checker half): the Section 2.4 worked example
reproduced exactly, N-from-H computation, the cell status rules (Section
5.1), row status/completeness (Section 5.2), and the 3 cross-column checks
(slot count mismatch, J date chain, J window coverage, L duplicate phones).
"""

import pytest

import app.validators  # noqa: F401 -- real validators, not the placeholder
from app.config import load_config
from app.consistency_checker import _decide_cell, check_row
from app.excel_reader import CellRecord
from app.models import Status
from app.response_parser import build_row_index
from app.row_matcher import RowMatch
from app.template_spec import SHEET_NAME


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _cell(row, col, text, sheet=SHEET_NAME):
    from openpyxl.utils import get_column_letter

    return CellRecord(
        sheet=sheet, cell=f"{get_column_letter(col)}{row}", row=row, col=col,
        raw_value=text or None, text=text, is_merged=False, merge_anchor=None,
        number_format="General", is_bold=False, has_comment=False, comment_text=None,
        data_validation=None,
    )


_COLUMN_LETTER_TO_INDEX = {l: i for i, l in enumerate("ABCDEFGHIJKLMNOPQRS", start=1)}

_FULL_ROW_DEFAULTS = {
    "A": "13", "B": "345061", "C": "SEHATGANJ", "D": "Bhopal", "E": "Bhopal",
    "F": "Sehatganj Village, Chainage 12+300, Bhopal City, 462001",
    "G": "BOT",
    "H": "1. Agency One\n2. Agency Two\n3. Agency Three\n4. Agency Four",
    "I": "1. EQ (3 months)\n2. Regular (1 year)\n3. EQ (3 months)\n4. Regular (1 year)",
    "J": (
        "1. 01/01/2021 - 10/11/2021\n2. 10/11/2021 - 10/11/2022\n"
        "3. 10/11/2022 - 10/02/2023\n4. 10/02/2023 - 14/01/2026"
    ),
    "K": "1. Rahul Sharma\n2. Amit Kumar\n3. Suresh Babu\n4. Vijay Singh",
    "L": "1. 9876543210\n2. 9876543211\n3. 9876543212\n4. 9876543213",
    "M": (
        "1. Toll Plaza Road, Bhopal\n2. Toll Plaza Road, Bhopal\n"
        "3. Toll Plaza Road, Bhopal\n4. Toll Plaza Road, Bhopal"
    ),
    "N": "1. Consultant A\n2. Consultant B\n3. Consultant C\n4. Consultant D",
    "O": "1. Team Lead A\n2. Team Lead B\n3. Team Lead C\n4. Team Lead D",
    "P": "1. HTMS A\n2. HTMS B\n3. HTMS C\n4. HTMS D",
    "Q": "1. 1500\n2. 1600\n3. 1700\n4. 1800",
    "R": "1. 100\n2. 110\n3. 120\n4. 130",
    "S": "some remark",
}


def _make_row(row_num: int, overrides: dict[str, str] | None = None) -> list[CellRecord]:
    values = dict(_FULL_ROW_DEFAULTS)
    if overrides:
        values.update(overrides)
    return [_cell(row_num, _COLUMN_LETTER_TO_INDEX[letter], text) for letter, text in values.items()]


def _check(row_num: int, overrides: dict[str, str] | None, cfg, identity_mismatches=None):
    cells = _make_row(row_num, overrides)
    row_index = build_row_index(cells, SHEET_NAME)
    row_match = RowMatch(
        template_s_no=13, template_plaza_code="345061", template_plaza_name="SEHATGANJ",
        template_ro="Bhopal", template_piu="Bhopal", response_row=row_num, match_strategy="s_no",
        identity_mismatches=identity_mismatches or [],
    )
    return check_row(row_index, row_match, cfg)


# ============================================================================
# The Section 2.4 worked example, verbatim
# ============================================================================


def test_section_2_4_worked_example_missing_slots(cfg):
    result = _check(15, {"L": "9876543210\n9876543211"}, cfg)  # only slots 1-2 filled
    assert result.n_contracts == 4
    l_result = result.per_column["L"]
    assert l_result.missing_slots == [3, 4]
    assert l_result.status == Status.PARTIAL
    assert l_result.valid_count == 2
    assert l_result.expected_count == 4


def test_fully_correct_row_is_all_complete(cfg):
    result = _check(15, None, cfg)
    assert result.n_contracts == 4
    assert all(cr.status == Status.COMPLETE for cr in result.per_column.values())
    assert result.status == Status.COMPLETE
    assert result.completeness == pytest.approx(1.0)


# ============================================================================
# N computation from column H
# ============================================================================


def test_n_is_zero_when_h_is_untouched_scaffold(cfg):
    from app.template_spec import get_column

    result = _check(15, {"H": get_column("H").scaffold_raw}, cfg)
    assert result.n_contracts == 0


def test_n_is_zero_when_h_is_na(cfg):
    result = _check(15, {"H": "N/A"}, cfg)
    assert result.n_contracts == 0


def test_n_counts_detected_slots_not_just_valid_ones(cfg):
    # slot 2 is garbage (no letters) -- still "declared", so N=3, not 2.
    result = _check(15, {"H": "1. Agency One\n2. 12\n3. Agency Three"}, cfg)
    assert result.n_contracts == 3
    assert result.per_column["H"].valid_count == 2
    assert result.per_column["H"].invalid_count == 1


# ============================================================================
# N == 0 forces every column to MISSING, even ones with real content
# ============================================================================


def test_n_zero_forces_missing_even_for_columns_with_content(cfg):
    result = _check(15, {"H": "", "L": "9876543210"}, cfg)
    assert result.n_contracts == 0
    assert result.per_column["L"].status == Status.MISSING
    # F/G/S are NOT tied to N -- they should be graded on their own merits.
    assert result.per_column["F"].status == Status.COMPLETE
    assert result.per_column["G"].status == Status.COMPLETE


# ============================================================================
# Cell status rules (Section 5.1)
# ============================================================================


def test_required_column_blank_is_missing(cfg):
    result = _check(15, {"L": ""}, cfg)
    assert result.per_column["L"].status == Status.MISSING
    assert result.per_column["L"].completeness == 0.0


def test_optional_remarks_blank_is_not_applicable(cfg):
    result = _check(15, {"S": ""}, cfg)
    assert result.per_column["S"].status == Status.NOT_APPLICABLE


def test_explicit_na_on_required_column_is_missing(cfg):
    # L is required -- there's no legitimate "doesn't apply" case (every
    # operating toll plaza has a manager to contact), so a whole-cell
    # "N/A" reads MISSING, not a free NOT_APPLICABLE pass. Confirmed
    # against real client data: KITLANA/NUNMATH write literal "NA"/"Not
    # Available" across whole required columns (N/O/P) while other
    # columns show the plaza clearly has real agencies under contract --
    # the human reviewer flags that as a problem, not an opt-out.
    result = _check(15, {"L": "N/A"}, cfg)
    assert result.per_column["L"].status == Status.MISSING
    assert result.per_column["L"].completeness == 0.0


def test_explicit_na_on_optional_remarks_is_not_applicable(cfg):
    # S (Remarks) is the one genuinely optional column -- the only place
    # a whole-cell "N/A" is still trusted as a deliberate non-answer.
    result = _check(15, {"S": "N/A"}, cfg)
    assert result.per_column["S"].status == Status.NOT_APPLICABLE
    assert result.per_column["S"].completeness is None


# ============================================================================
# Per-slot NA/"Not Assigned" -- found via real client data (MAUHARI): a
# numbered list where SOME entries are real and others say "Not Assigned".
# Same underlying principle as a *whole-cell* "N/A" on a required column
# (above): a non-answer never counts toward valid_count, and never reads
# INVALID either (it's not a wrong value, it's an absent one) -- it drags
# the cell to MISSING/PARTIAL.
# ============================================================================


def test_per_slot_not_assigned_is_missing_not_valid(cfg):
    result = _check(15, {"N": "1. Consultant A\n2. Not Assigned\n3. Consultant C\n4. Consultant D"}, cfg)
    n_result = result.per_column["N"]
    assert n_result.status == Status.PARTIAL
    assert n_result.missing_slots == [2]
    assert n_result.valid_count == 3
    assert n_result.invalid_count == 0  # dropped, not marked wrong


def test_per_slot_not_assigned_uppercase_matches_real_client_phrasing(cfg):
    result = _check(15, {"O": "1. Team Lead A\n2. TEAM LEAD B\n3. NOT ASSIGNED\n4. Team Lead D"}, cfg)
    assert result.per_column["O"].missing_slots == [3]


@pytest.mark.parametrize("phrase", ["Not Assigned", "Unassigned", "Not Available", "N/A", "NA", "Nil", "-"])
def test_per_slot_na_variants_all_dropped(cfg, phrase):
    result = _check(15, {"K": f"1. Rahul Sharma\n2. {phrase}\n3. Suresh Babu\n4. Vijay Singh"}, cfg)
    assert result.per_column["K"].missing_slots == [2]


def test_per_slot_all_not_assigned_reads_as_missing_not_not_applicable(cfg):
    # Every slot is a non-answer -- must read as a genuinely unfilled
    # required column (MISSING), not slip through as NOT_APPLICABLE the
    # way a literal whole-cell "N/A" would.
    result = _check(15, {"P": "\n".join(f"{i}. Not Assigned" for i in range(1, 5))}, cfg)
    p_result = result.per_column["P"]
    assert p_result.status == Status.MISSING
    assert p_result.valid_count == 0


def test_all_invalid_is_invalid_status(cfg):
    result = _check(15, {"L": "1. abc\n2. def\n3. ghi\n4. jkl"}, cfg)
    assert result.per_column["L"].status == Status.INVALID
    assert result.per_column["L"].completeness == 0.0


def test_partial_valid_is_partial_status(cfg):
    result = _check(15, {"L": "1. 9876543210\n2. abc\n3. 9876543212\n4. abc"}, cfg)
    l_result = result.per_column["L"]
    assert l_result.status == Status.PARTIAL
    assert l_result.valid_count == 2
    assert l_result.invalid_count == 2
    assert l_result.completeness == pytest.approx(0.5)


def test_decide_cell_defensive_review_fallback_never_crashes():
    # Contrived: expected_count None without is_blank -- shouldn't happen in
    # practice (see consistency_checker.py's comment), but must not crash.
    status, completeness, reason = _decide_cell(
        expected_count=None, detected=2, valid=1, is_blank=False, is_na=False,
        required=True, missing_slots=[],
    )
    assert status == Status.REVIEW


# ============================================================================
# Row status (Section 5.2): worst cell status, REVIEW if identity altered
# ============================================================================


def test_row_status_is_worst_cell_status(cfg):
    result = _check(15, {"L": "1. abc\n2. def\n3. ghi\n4. jkl"}, cfg)  # L becomes INVALID
    assert result.status == Status.INVALID


def test_row_status_escalates_to_review_on_identity_mismatch(cfg):
    result = _check(15, None, cfg, identity_mismatches=["Plaza Name: expected 'SEHATGANJ', got 'SEHATGANJ X'"])
    assert result.status == Status.REVIEW  # would otherwise be COMPLETE


def test_row_status_stays_worse_than_review_if_already_worse(cfg):
    # L is INVALID (more severe than REVIEW) -- an identity mismatch on top
    # shouldn't *downgrade* the row status back to REVIEW.
    result = _check(
        15, {"L": "1. abc\n2. def\n3. ghi\n4. jkl"}, cfg,
        identity_mismatches=["Plaza Name: expected 'SEHATGANJ', got 'X'"],
    )
    assert result.status == Status.INVALID


def test_row_status_escalates_to_review_on_consistency_finding(cfg):
    # L is only PARTIAL on its own (cell severity 1), but a genuinely
    # missing slot also produces a slot_count_mismatch finding (REVIEW,
    # severity 2) -- the row must reflect the finding's severity, not just
    # the worst individual cell's, or the tool's central purpose (surfacing
    # exactly this kind of gap) would be invisible at the row level.
    result = _check(15, {"L": "9876543210\n9876543211"}, cfg)  # 2 of 4 phones
    assert result.per_column["L"].status == Status.PARTIAL
    assert any(f.kind == "slot_count_mismatch" for f in result.consistency_findings)
    assert result.status == Status.REVIEW


def test_row_status_review_from_finding_does_not_downgrade_worse_cell_status(cfg):
    # If some OTHER cell is already INVALID (severity 3), a REVIEW-level
    # finding elsewhere must not pull the row status back down to REVIEW.
    result = _check(
        15,
        {"K": "1. 123\n2. 456\n3. 789\n4. 000", "L": "9876543210\n9876543211"},
        cfg,
    )
    assert result.per_column["K"].status == Status.INVALID
    assert any(f.kind == "slot_count_mismatch" for f in result.consistency_findings)
    assert result.status == Status.INVALID


# ============================================================================
# Row completeness (Section 5.2 formula)
# ============================================================================


def test_row_completeness_formula(cfg):
    # Only L is short (2 of 4 valid); all other 10 slotted columns fully valid.
    result = _check(15, {"L": "9876543210\n9876543211"}, cfg)
    total_valid = 4 * 10 + 2  # 10 fully-valid slotted columns + L's 2
    denominator = 4 * 11  # N=4 across 11 slotted columns
    assert result.completeness == pytest.approx(total_valid / denominator)


def test_row_completeness_never_exceeds_100_percent_on_oversupply(cfg):
    # H declares 2 agencies, but L has 4 phone numbers -- oversupply on one
    # column must not push the row's overall completeness above 100%.
    result = _check(15, {"H": "1. Agency One\n2. Agency Two", "L": "9876543210\n9876543211\n9876543212\n9876543213"}, cfg)
    assert result.n_contracts == 2
    assert result.per_column["L"].valid_count == 4  # the raw count is still honest
    assert result.completeness <= 1.0
    assert result.completeness == pytest.approx(1.0)  # every other column fully valid too


def test_row_completeness_is_none_when_n_is_zero(cfg):
    result = _check(15, {"H": ""}, cfg)
    assert result.completeness is None


# ============================================================================
# Consistency findings: slot count mismatch
# ============================================================================


def test_slot_count_mismatch_finding_present_for_partial_column(cfg):
    result = _check(15, {"L": "9876543210\n9876543211"}, cfg)
    findings = [f for f in result.consistency_findings if f.kind == "slot_count_mismatch"]
    assert len(findings) == 1
    assert findings[0].column == "L"
    assert "3, 4" in findings[0].message


def test_no_slot_count_mismatch_when_fully_filled(cfg):
    result = _check(15, None, cfg)
    findings = [f for f in result.consistency_findings if f.kind == "slot_count_mismatch"]
    assert findings == []


def test_slot_count_mismatch_fires_when_required_column_is_explicitly_na(cfg):
    # L is required, so a whole-cell "N/A" is a genuine gap (MISSING), not
    # a trusted opt-out -- the slot_count_mismatch finding must fire here,
    # same as any other unfilled required column.
    result = _check(15, {"L": "N/A"}, cfg)
    assert result.per_column["L"].status == Status.MISSING
    assert result.per_column["L"].missing_slots
    findings = [f for f in result.consistency_findings if f.kind == "slot_count_mismatch" and f.column == "L"]
    assert len(findings) == 1


def test_no_slot_count_mismatch_when_optional_column_is_explicitly_na(cfg):
    # S (Remarks) is the one genuinely optional, non-slotted column -- it
    # never participates in slot_count_mismatch checking at all (that
    # check only runs over the slotted columns), so this is really just
    # confirming a whole-cell N/A there stays a clean NOT_APPLICABLE with
    # no side effects.
    result = _check(15, {"S": "N/A"}, cfg)
    assert result.per_column["S"].status == Status.NOT_APPLICABLE
    findings = [f for f in result.consistency_findings if f.kind == "slot_count_mismatch" and f.column == "S"]
    assert findings == []


# ============================================================================
# Consistency findings: date chain continuity
# ============================================================================


def test_date_chain_gap_detected(cfg):
    # Gap between slot 1 end (10/11/2021) and slot 2 start (01/01/2022).
    result = _check(15, {"J": "1. 10/08/2021 - 10/11/2021\n2. 01/01/2022 - 14/01/2026"}, cfg)
    findings = [f for f in result.consistency_findings if f.kind == "date_chain_gap"]
    assert len(findings) == 1
    assert "slot 1" in findings[0].message and "slot 2" in findings[0].message


def test_date_chain_no_gap_within_tolerance(cfg):
    # Contiguous chain (end of one = start of next) should have zero findings.
    result = _check(
        15,
        {"J": "1. 10/08/2021 - 10/11/2021\n2. 10/11/2021 - 10/11/2022\n3. 10/11/2022 - 10/02/2023\n4. 10/02/2023 - 14/01/2026"},
        cfg,
    )
    findings = [f for f in result.consistency_findings if "date_chain" in f.kind]
    assert findings == []


def test_date_chain_overlap_detected(cfg):
    # Slot 2 starts before slot 1 ends.
    result = _check(15, {"J": "1. 10/08/2021 - 10/11/2021\n2. 01/10/2021 - 14/01/2026"}, cfg)
    findings = [f for f in result.consistency_findings if f.kind == "date_chain_overlap"]
    assert len(findings) == 1


# ============================================================================
# Consistency findings: window coverage
# ============================================================================


def test_window_coverage_gap_at_start_detected(cfg):
    result = _check(15, {"J": "1. 01/06/2021 - 14/01/2026"}, cfg)
    findings = [f for f in result.consistency_findings if f.kind == "date_window_coverage"]
    assert any("starts" in f.message for f in findings)


def test_window_coverage_gap_at_end_detected(cfg):
    result = _check(15, {"J": "1. 01/01/2021 - 01/06/2023"}, cfg)
    findings = [f for f in result.consistency_findings if f.kind == "date_window_coverage"]
    assert any("ends" in f.message for f in findings)


def test_window_fully_covered_has_no_finding(cfg):
    result = _check(15, {"J": "1. 01/01/2021 - 14/01/2026"}, cfg)
    findings = [f for f in result.consistency_findings if f.kind == "date_window_coverage"]
    assert findings == []


# ============================================================================
# Consistency findings: duplicate phones
# ============================================================================


def test_duplicate_phone_across_all_agencies_flagged(cfg):
    result = _check(15, {"L": "1. 9876543210\n2. 9876543210\n3. 9876543210\n4. 9876543210"}, cfg)
    findings = [f for f in result.consistency_findings if f.kind == "duplicate_phone"]
    assert len(findings) == 1
    assert findings[0].column == "L"


def test_distinct_phones_not_flagged_as_duplicate(cfg):
    result = _check(15, None, cfg)
    findings = [f for f in result.consistency_findings if f.kind == "duplicate_phone"]
    assert findings == []
