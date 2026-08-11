"""Phase 9 gate: the 2 worked examples from BUILD_PLAN.md Phase 9, plus
NA handling, truncation notes, and the duplicates_are_invalid config gate."""

import pytest

import app.validators  # noqa: F401 -- need real validators, not the placeholder
from app.config import load_config
from app.excel_reader import CellRecord
from app.models import CountSource, ExpectedCount, FieldSpec, FieldType
from app.response_parser import parse_response
from app.value_splitter import NA_SENTINEL


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _spec(field_type=FieldType.PHONE, expected_count=10) -> FieldSpec:
    return FieldSpec(
        sheet="Sheet1",
        cell="D15",
        field_name="Contact Numbers",
        field_type=field_type,
        field_type_confidence=1.0,
        expected=ExpectedCount(count=expected_count, source=CountSource.EXPLICIT_INSTRUCTION, confidence=0.95),
        required=True,
        source="test",
        context_text="",
    )


def _cell(text) -> CellRecord:
    return CellRecord(
        sheet="Sheet1", cell="D15", row=15, col=4, raw_value=text or None, text=text,
        is_merged=False, merge_anchor=None, number_format="General", is_bold=False,
        has_comment=False, comment_text=None, data_validation=None,
    )


# ============================================================================
# The 2 Done-when examples, verbatim
# ============================================================================


def test_mixed_valid_and_invalid_phones(cfg):
    cell = _cell("9876543210\n9876543211\n9876\n9876543213")
    values, note = parse_response(_spec(), cell, cfg)

    assert len(values) == 4
    valid = [v for v in values if v.verdict.is_valid]
    invalid = [v for v in values if not v.verdict.is_valid]
    assert len(valid) == 3
    assert len(invalid) == 1
    assert invalid[0].raw == "9876"


def test_repeated_value_five_times_yields_one_valid_four_duplicates(cfg):
    cell = _cell("\n".join(["9876543210"] * 5))
    values, note = parse_response(_spec(), cell, cfg)

    assert len(values) == 5
    valid = [v for v in values if v.verdict.is_valid]
    invalid = [v for v in values if not v.verdict.is_valid]
    assert len(valid) == 1
    assert len(invalid) == 4
    assert all("duplicate of value #1" in v.verdict.reason for v in invalid)


# ============================================================================
# No response / blank
# ============================================================================


def test_no_cell_returns_empty(cfg):
    values, note = parse_response(_spec(), None, cfg)
    assert values == []
    assert note == ""


def test_blank_cell_text_returns_empty(cfg):
    values, note = parse_response(_spec(), _cell(""), cfg)
    assert values == []
    assert note == ""


# ============================================================================
# N/A sentinel
# ============================================================================


def test_na_token_returns_single_flagged_value(cfg):
    values, note = parse_response(_spec(), _cell("N/A"), cfg)
    assert len(values) == 1
    assert values[0].raw == NA_SENTINEL
    assert values[0].verdict.is_valid is True


# ============================================================================
# Truncation note
# ============================================================================


def test_truncation_note_set_when_cap_hit():
    cfg = load_config(overrides={"parsing": {"max_values_per_cell": 3}})
    cell = _cell("\n".join(f"987654321{i}" for i in range(10)))
    values, note = parse_response(_spec(), cell, cfg)
    assert len(values) == 3
    assert "truncated" in note


def test_no_truncation_note_under_cap(cfg):
    cell = _cell("9876543210\n9876543211")
    values, note = parse_response(_spec(), cell, cfg)
    assert note == ""


# ============================================================================
# Indexing and dedup config gate
# ============================================================================


def test_indices_are_one_based_in_order(cfg):
    cell = _cell("9876543210\n9876543211\n9876543212")
    values, note = parse_response(_spec(), cell, cfg)
    assert [v.index for v in values] == [1, 2, 3]


def test_duplicates_are_invalid_false_disables_dedup():
    cfg = load_config(overrides={"parsing": {"duplicates_are_invalid": False}})
    cell = _cell("\n".join(["9876543210"] * 3))
    values, note = parse_response(_spec(), cell, cfg)
    assert all(v.verdict.is_valid for v in values)


def test_invalid_values_do_not_participate_in_dedup(cfg):
    # Two malformed "9876" entries shouldn't be marked as duplicates of each
    # other -- they're independently invalid on their own shape, not a
    # repeated-valid-value QC signal.
    cell = _cell("9876\n9876")
    values, note = parse_response(_spec(), cell, cfg)
    assert all(not v.verdict.is_valid for v in values)
    assert all("duplicate" not in v.verdict.reason for v in values)
