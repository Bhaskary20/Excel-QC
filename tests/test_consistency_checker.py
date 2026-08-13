"""Phase F gate (consistency_checker half): the Section 2.4 worked example
reproduced exactly, N-from-H computation, the cell status rules (Section
5.1), row status/completeness (Section 5.2), and the one remaining
cross-column check (slot count mismatch). Date chain/window coverage and
duplicate-phone checks were removed at the user's request -- kept simple.
"""

import dataclasses

import pytest

import app.validators  # noqa: F401 -- real validators, not the placeholder
from app.config import load_config
from app.consistency_checker import _decide_cell, _find_merged_with_rows, check_row
from app.excel_reader import CellRecord
from app.models import Status
from app.response_parser import build_row_index
from app.row_matcher import RowMatch
from app.template_spec import SHEET_NAME, get_column


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


def test_n_counts_all_declared_slots(cfg):
    # slot 2 ("12", no letters) is still "declared" -- N=3. H is
    # presence-only now, so it's actually valid too, but N (agency count)
    # was always meant to count declared slots, not filter by validity.
    result = _check(15, {"H": "1. Agency One\n2. 12\n3. Agency Three"}, cfg)
    assert result.n_contracts == 3
    assert result.per_column["H"].valid_count == 3
    assert result.per_column["H"].invalid_count == 0


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


def test_all_invalid_is_invalid_status():
    # L/K/H etc. are all presence-only now (no real content can fail their
    # validators), so this exercises _decide_cell directly rather than
    # through a column whose real validator can no longer produce INVALID.
    status, completeness, _ = _decide_cell(
        expected_count=4, detected=4, valid=0, is_blank=False, is_na=False,
        required=True, missing_slots=[],
    )
    assert status == Status.INVALID
    assert completeness == 0.0


def test_partial_valid_is_partial_status():
    status, completeness, _ = _decide_cell(
        expected_count=4, detected=4, valid=2, is_blank=False, is_na=False,
        required=True, missing_slots=[2, 4],
    )
    assert status == Status.PARTIAL
    assert completeness == pytest.approx(0.5)


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
    # G is the only column left whose real validator can still produce
    # INVALID from ordinary content (L/K/H etc. are presence-only now).
    result = _check(15, {"G": "Nonsense Type"}, cfg)
    assert result.status == Status.INVALID


def test_row_status_escalates_to_review_on_identity_mismatch(cfg):
    result = _check(15, None, cfg, identity_mismatches=["Plaza Name: expected 'SEHATGANJ', got 'SEHATGANJ X'"])
    assert result.status == Status.REVIEW  # would otherwise be COMPLETE


def test_row_status_stays_worse_than_review_if_already_worse(cfg):
    # G is INVALID (more severe than REVIEW) -- an identity mismatch on top
    # shouldn't *downgrade* the row status back to REVIEW.
    result = _check(
        15, {"G": "Nonsense Type"}, cfg,
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
        {"G": "Nonsense Type", "L": "9876543210\n9876543211"},  # G invalid, L short (2 of 4)
        cfg,
    )
    assert result.per_column["G"].status == Status.INVALID
    assert any(f.kind == "slot_count_mismatch" for f in result.consistency_findings)
    assert result.status == Status.INVALID


# ============================================================================
# AE/IE + HTMS (N/O/P) group status: not compared to agency count, graded
# as a group instead -- 1-2 of 3 answered is PARTIAL, none answered is
# MISSING (incomplete data), all 3 answered is COMPLETE regardless of how
# many of the N agencies each one covers.
# ============================================================================


def test_aeie_htms_shortfall_no_longer_blocks_full_completion(cfg):
    # Each of N/O/P has only 1 of 4 slots filled -- a real answer, just not
    # one per agency. That alone must no longer prevent the row from being
    # COMPLETE, since a single AE/IE consultant can legitimately cover
    # several agency-contract periods.
    result = _check(15, {"N": "Consultant A", "O": "Team Lead A", "P": "HTMS A"}, cfg)
    assert result.per_column["N"].status == Status.PARTIAL  # per-column detail still shows the shortfall
    assert not any(f.column in ("N", "O", "P") for f in result.consistency_findings)
    assert result.status == Status.COMPLETE


def test_aeie_htms_all_three_blank_is_missing(cfg):
    # Whole-cell non-answers on all three -- no real data anywhere in the
    # group -- must read as incomplete data (MISSING), not a free pass.
    result = _check(15, {"N": "NA", "O": "Not Assigned", "P": "N/A"}, cfg)
    assert result.per_column["N"].status == Status.MISSING
    assert result.status == Status.MISSING


def test_aeie_htms_some_answered_some_blank_is_partial(cfg):
    # N has real data, O and P don't -- 1 of 3 answered -> PARTIAL, not
    # dragged all the way down to MISSING just because two of three are blank.
    result = _check(15, {"O": "NA", "P": "NA"}, cfg)
    assert result.status == Status.PARTIAL


def test_aeie_htms_never_produces_slot_count_mismatch_finding(cfg):
    result = _check(15, {"N": "Consultant A", "O": "NA", "P": "NA"}, cfg)
    findings = [f for f in result.consistency_findings if f.kind == "slot_count_mismatch"]
    assert all(f.column not in ("N", "O", "P") for f in findings)


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
# merged_with_rows: two adjoining plazas sharing one merged-cell answer
# (real client data, tests/UPSTF Case 13.08.2026.xlsx: KUCCHADI/OKHAMADI
# have G..P and S merged across both rows, F/Q/R filled independently)
# ============================================================================


def test_find_merged_with_rows_detects_cross_row_merge(cfg):
    anchor_row, merged_row = 34, 35
    h_index = get_column("H").index
    f_index = get_column("F").index

    anchor_h = dataclasses.replace(_cell(anchor_row, h_index, "1. Agency One"), is_merged=True, merge_anchor=f"H{anchor_row}")
    merged_h = dataclasses.replace(_cell(merged_row, h_index, "1. Agency One"), is_merged=True, merge_anchor=f"H{anchor_row}")
    merged_f = _cell(merged_row, f_index, "Some Village")  # independent per-row value, not merged

    row_index = {
        (anchor_row, h_index): anchor_h,
        (merged_row, h_index): merged_h,
        (merged_row, f_index): merged_f,
    }
    assert _find_merged_with_rows(row_index, merged_row) == (anchor_row,)
    # The anchor row's own cell points at itself -- that's not "merged with
    # another row", so the anchor must not report a link to itself.
    assert _find_merged_with_rows(row_index, anchor_row) == ()


def test_find_merged_with_rows_empty_when_nothing_merged(cfg):
    result = _check(15, None, cfg)
    assert result.merged_with_rows == ()


def test_check_row_populates_merged_with_rows_end_to_end(cfg):
    anchor_row, merged_row = 34, 35
    independent_columns = {"F", "Q", "R"}  # filled per-plaza, not merged, same as real data

    cells = []
    for letter, text in _FULL_ROW_DEFAULTS.items():
        if letter in ("A", "B", "C", "D", "E"):
            continue  # KEY columns aren't part of merged_with_rows detection
        col = _COLUMN_LETTER_TO_INDEX[letter]
        cell = _cell(merged_row, col, text)
        if letter not in independent_columns:
            cell = dataclasses.replace(cell, is_merged=True, merge_anchor=f"{letter}{anchor_row}")
        cells.append(cell)

    row_index = build_row_index(cells, SHEET_NAME)
    row_match = RowMatch(
        template_s_no=14, template_plaza_code="336009", template_plaza_name="OKHAMADI",
        template_ro="Gujarat", template_piu="Rajkot", response_row=merged_row, match_strategy="s_no",
        identity_mismatches=[],
    )
    result = check_row(row_index, row_match, cfg)
    assert result.merged_with_rows == (anchor_row,)
