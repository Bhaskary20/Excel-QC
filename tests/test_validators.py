"""Phase D gate: >=2 valid and >=2 invalid cases per ValueType, using the
real ColumnSpecs from template_spec so tests stay grounded in the actual
template rather than hand-built specs that could drift from it."""

import pytest

import app.validators  # noqa: F401 -- import side effect registers real validators
from app.config import load_config
from app.models import get_validator
from app.template_spec import ValueType, get_column


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _validate(letter, value, cfg):
    spec = get_column(letter)
    return get_validator(spec.value_type)(value, cfg, spec)


# ============================================================================
# TEXT -- H, I, N, P, S. At the user's request, none of these check content
# any more -- only whether a slot has something in it (that's decided
# upstream in slot_parser.py, before a value ever reaches a validator).
# ============================================================================


@pytest.mark.parametrize("value", ["ABC Toll Ltd", "XYZ Infra Corp", "ab", "123", "@#$"])
def test_text_accepts_anything_non_empty(cfg, value):
    assert _validate("H", value, cfg).is_valid


@pytest.mark.parametrize("value", ["ok", "x", "Client left a short note"])
def test_text_optional_remarks_is_lenient(cfg, value):
    assert _validate("S", value, cfg).is_valid


# ============================================================================
# COMPOSITE_LOCATION -- F
# ============================================================================


def test_composite_location_full_shape_no_warning(cfg):
    result = _validate("F", "Nellore Village, Chainage 12+300, Nellore City, 524001", cfg)
    assert result.is_valid
    assert result.reason == ""


def test_composite_location_partial_shape_warns_but_valid(cfg):
    result = _validate("F", "Nellore Village, 524001", cfg)
    assert result.is_valid
    assert result.reason != ""


@pytest.mark.parametrize("value", ["12345", "---"])
def test_composite_location_no_letters_invalid(cfg, value):
    assert not _validate("F", value, cfg).is_valid


# ============================================================================
# ENUM -- G (Plaza Type) only now. I (EQ/Regular) moved to TEXT (presence
# only) at the user's request -- real data sometimes has a contract-model
# term there (e.g. "OMT", "TOT") instead of EQ/Regular, which isn't a typo,
# just not what the column asks for, and only slot count should matter.
# ============================================================================


@pytest.mark.parametrize("value", ["BOT", "public funded", "Invit", "INVIT", "  TOT  "])
def test_plaza_type_enum_valid(cfg, value):
    assert _validate("G", value, cfg).is_valid


@pytest.mark.parametrize("value", ["Private", "HAM", "EPC"])
def test_plaza_type_enum_invalid(cfg, value):
    assert not _validate("G", value, cfg).is_valid


# "PF"/"FP" are the standard NHAI shorthand for Public Funded -- found via
# real client data, where the overwhelming majority of responses use the
# abbreviation rather than the spelled-out form.
@pytest.mark.parametrize(
    "value,expected_normalized",
    [
        ("PF", "Public Funded"),
        ("pf", "Public Funded"),
        ("FP", "Public Funded"),
        ("Public funded (PF)", "Public Funded"),
        ("PF (HAM)", "Public Funded"),
    ],
)
def test_plaza_type_pf_abbreviation_aliases(cfg, value, expected_normalized):
    result = _validate("G", value, cfg)
    assert result.is_valid
    assert result.normalized == expected_normalized


@pytest.mark.parametrize("value", ["EQ", "Regular", "OMT", "TOT", "Monthly", "anything"])
def test_eq_regular_column_i_accepts_anything_non_empty(cfg, value):
    assert _validate("I", value, cfg).is_valid


# ============================================================================
# NAME -- K, O. At the user's request, content is no longer checked -- a
# malformed or garbled name still counts as "an answer".
# ============================================================================


@pytest.mark.parametrize("value", ["Rahul Sharma", "Amit Kumar", "O'Brien", "12345", "-", "@#$"])
def test_name_accepts_anything_non_empty(cfg, value):
    assert _validate("K", value, cfg).is_valid


def test_name_columns_k_and_o_share_the_same_rule(cfg):
    assert _validate("K", "Rahul Sharma", cfg).is_valid
    assert _validate("O", "Rahul Sharma", cfg).is_valid


# ============================================================================
# PHONE -- L. At the user's request, content is no longer checked -- a
# malformed number still counts as "an answer".
# ============================================================================


@pytest.mark.parametrize("value", ["9876543210", "+91 98765 43210", "09876543210", "9876", "1234567890"])
def test_phone_accepts_anything_non_empty(cfg, value):
    assert _validate("L", value, cfg).is_valid


# ============================================================================
# DATE_RANGE -- J. At the user's request, format/order/window is no longer
# validated at all -- any non-empty slot counts as answered, typo'd,
# malformed, or otherwise. Only slot *count* vs. agency count still matters
# (that's the slot_count_mismatch check in consistency_checker.py, not
# anything here).
# ============================================================================


@pytest.mark.parametrize(
    "value",
    [
        "10/08/2021 - 14/01/2026",
        "01/01/2021 to 14/01/2026",
        "From (10/08/2021) - To (14/01/2026)",
        "01/01/2019 - 14/01/2026",  # outside the old contract window -- no longer checked
        "10/08/2021",  # a single date, not a range -- no longer checked
        "14/01/2026 - 10/08/2021",  # end before start -- no longer checked
        "21/09//2023",  # doubled-slash typo -- no longer checked
        "14/072022",  # missing-slash typo -- no longer checked
        "not a date range at all",  # not date-shaped at all -- no longer checked
    ],
)
def test_date_range_accepts_anything_non_empty(cfg, value):
    result = _validate("J", value, cfg)
    assert result.is_valid
    assert result.normalized == value
    assert result.reason == ""


# ============================================================================
# ADDRESS -- M. At the user's request, content is no longer checked.
# ============================================================================


@pytest.mark.parametrize("value", ["123 Main Street, Springfield", "H.No 4-5, Toll Colony, Nellore", "short", "1234567890"])
def test_address_accepts_anything_non_empty(cfg, value):
    assert _validate("M", value, cfg).is_valid


# ============================================================================
# NUMBER -- Q, R (traffic counts). At the user's request, content is no
# longer checked -- a typo'd, non-numeric, negative, or zero figure all
# still count as "an answer".
# ============================================================================


@pytest.mark.parametrize("value", ["1500", "1,500", "2500 veh", "3000 PCU", "abc", "-100", "0"])
def test_number_accepts_anything_non_empty(cfg, value):
    assert _validate("Q", value, cfg).is_valid


def test_number_columns_q_and_r_share_the_same_rule(cfg):
    assert _validate("Q", "1500", cfg).is_valid
    assert _validate("R", "1500", cfg).is_valid


# ============================================================================
# INTEGER -- registered for completeness (A/S.No is a KEY column, never
# actually run through this in the real pipeline)
# ============================================================================


@pytest.mark.parametrize("value", ["123", "1,234"])
def test_integer_valid(cfg, value):
    spec = get_column("A")
    assert get_validator(ValueType.INTEGER)(value, cfg, spec).is_valid


@pytest.mark.parametrize("value", ["abc", ""])
def test_integer_invalid(cfg, value):
    spec = get_column("A")
    assert not get_validator(ValueType.INTEGER)(value, cfg, spec).is_valid


# ============================================================================
# Cross-cutting: never raises, never echoes the raw value in `reason`
# ============================================================================


def test_every_registered_validator_never_raises(cfg):
    weird_inputs = ["", " ", "\n", "😀", "a" * 200, "NULL", "undefined", "0" * 50, "1/2/3/4/5"]
    for value_type in ValueType:
        validator = get_validator(value_type)
        # use a column that actually has this value_type, or a stand-in spec
        matching = [c for c in ["A", "B", "F", "G", "H", "I", "J", "K", "L", "M", "Q", "S"]]
        spec = next((get_column(c) for c in matching if get_column(c).value_type == value_type), get_column("H"))
        for value in weird_inputs:
            result = validator(value, cfg, spec)
            assert result.__class__.__name__ == "ValueVerdict"


def test_invalid_reasons_never_echo_the_raw_value():
    # G is the only column left with a real fail path (I, K, L, M, Q are
    # all presence-only now and never actually fail).
    cfg = load_config()
    distinctive_value = "ZzXyQ12345Invalid"
    result = _validate("G", distinctive_value, cfg)
    assert not result.is_valid
    assert distinctive_value not in result.reason
