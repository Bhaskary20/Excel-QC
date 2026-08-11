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
# TEXT -- H/N/P (required) vs S (optional Remarks)
# ============================================================================


@pytest.mark.parametrize("value", ["ABC Toll Ltd", "XYZ Infra Corp"])
def test_text_required_valid(cfg, value):
    assert _validate("H", value, cfg).is_valid


@pytest.mark.parametrize("value", ["ab", "123"])
def test_text_required_invalid(cfg, value):
    assert not _validate("H", value, cfg).is_valid


@pytest.mark.parametrize("value", ["ok", "x", "Client left a short note"])
def test_text_optional_remarks_is_lenient(cfg, value):
    assert _validate("S", value, cfg).is_valid


def test_text_optional_remarks_rejects_only_empty(cfg):
    assert not _validate("S", "", cfg).is_valid


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
# ENUM -- G (Plaza Type) and I (EQ/Regular), disambiguated by spec
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


@pytest.mark.parametrize(
    "value,expected_normalized",
    [
        ("EQ (3 months)", "EQ (3 months)"),
        ("Regular (1 year)", "Regular (1 year)"),
        ("3 months", "EQ (3 months)"),
        ("regular", "Regular (1 year)"),
        ("1 year", "Regular (1 year)"),
    ],
)
def test_eq_regular_enum_valid_including_aliases(cfg, value, expected_normalized):
    result = _validate("I", value, cfg)
    assert result.is_valid
    assert result.normalized == expected_normalized


@pytest.mark.parametrize("value", ["Monthly", "Yearly", "Quarterly"])
def test_eq_regular_enum_invalid(cfg, value):
    assert not _validate("I", value, cfg).is_valid


# ============================================================================
# NAME -- K, O
# ============================================================================


@pytest.mark.parametrize("value", ["Rahul Sharma", "Amit Kumar", "O'Brien"])
def test_name_valid(cfg, value):
    assert _validate("K", value, cfg).is_valid


@pytest.mark.parametrize("value", ["12345", "-", "@#$"])
def test_name_invalid(cfg, value):
    assert not _validate("K", value, cfg).is_valid


def test_name_columns_k_and_o_share_the_same_rule(cfg):
    assert _validate("K", "Rahul Sharma", cfg).is_valid
    assert _validate("O", "Rahul Sharma", cfg).is_valid


# ============================================================================
# PHONE -- L
# ============================================================================


@pytest.mark.parametrize("value", ["9876543210", "+91 98765 43210", "09876543210"])
def test_phone_valid(cfg, value):
    assert _validate("L", value, cfg).is_valid


@pytest.mark.parametrize("value", ["9876", "1234567890", "98765432101"])
def test_phone_invalid(cfg, value):
    assert not _validate("L", value, cfg).is_valid


def test_phone_invalid_reason_does_not_echo_value(cfg):
    result = _validate("L", "9876", cfg)
    assert "9876" not in result.reason


# ============================================================================
# DATE_RANGE -- J
# ============================================================================


@pytest.mark.parametrize(
    "value",
    ["10/08/2021 - 14/01/2026", "01/01/2021 to 14/01/2026", "From (10/08/2021) - To (14/01/2026)"],
)
def test_date_range_valid_within_window(cfg, value):
    result = _validate("J", value, cfg)
    assert result.is_valid
    assert result.reason == ""


def test_date_range_valid_but_outside_window_warns(cfg):
    result = _validate("J", "01/01/2019 - 14/01/2026", cfg)
    assert result.is_valid
    assert "window" in result.reason


@pytest.mark.parametrize(
    "value",
    ["10/08/2021", "14/01/2026 - 10/08/2021", "not a date range at all"],
)
def test_date_range_invalid(cfg, value):
    assert not _validate("J", value, cfg).is_valid


# ============================================================================
# ADDRESS -- M
# ============================================================================


@pytest.mark.parametrize("value", ["123 Main Street, Springfield", "H.No 4-5, Toll Colony, Nellore"])
def test_address_valid(cfg, value):
    assert _validate("M", value, cfg).is_valid


@pytest.mark.parametrize("value", ["short", "1234567890"])
def test_address_invalid(cfg, value):
    assert not _validate("M", value, cfg).is_valid


# ============================================================================
# NUMBER -- Q, R (traffic counts)
# ============================================================================


@pytest.mark.parametrize("value", ["1500", "1,500", "2500 veh", "3000 PCU"])
def test_number_valid(cfg, value):
    assert _validate("Q", value, cfg).is_valid


@pytest.mark.parametrize("value", ["abc", "-100", "0"])
def test_number_invalid(cfg, value):
    assert not _validate("Q", value, cfg).is_valid


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
    cfg = load_config()
    distinctive_value = "ZzXyQ12345Invalid"
    for letter in ["G", "I", "K", "L", "M", "Q"]:
        result = _validate(letter, distinctive_value, cfg)
        if not result.is_valid:
            assert distinctive_value not in result.reason, f"column {letter} echoed the raw value in its reason"
