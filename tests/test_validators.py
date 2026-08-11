"""Phase 4 gate: every registered type has >=2 valid and >=2 invalid cases,
plus the two exact assertions from BUILD_PLAN.md's Phase 4 Done-when."""

import pytest

import app.validators  # noqa: F401 -- import side effect registers real validators
from app.config import load_config
from app.models import FieldType, get_type_profile


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _validate(field_type, value, cfg):
    return get_type_profile(field_type).validator(value, cfg)


# ============================================================================
# Build-plan Done-when assertions, verbatim
# ============================================================================


def test_amount_indian_grouping_normalizes(cfg):
    result = _validate(FieldType.AMOUNT, "₹2,50,000", cfg)
    assert result.is_valid
    assert result.normalized == "250000"


def test_phone_with_country_code_and_spaces_normalizes(cfg):
    result = _validate(FieldType.PHONE, "+91 98765 43210", cfg)
    assert result.is_valid
    assert result.normalized == "9876543210"


# ============================================================================
# PHONE
# ============================================================================


@pytest.mark.parametrize("value", ["9876543210", "9876543211", "+919876543210", "09876543210"])
def test_phone_valid(cfg, value):
    assert _validate(FieldType.PHONE, value, cfg).is_valid


@pytest.mark.parametrize("value", ["9876", "98765432101", "abcdefghij", "1876543210"])
def test_phone_invalid(cfg, value):
    assert not _validate(FieldType.PHONE, value, cfg).is_valid


def test_phone_invalid_reason_does_not_echo_value(cfg):
    result = _validate(FieldType.PHONE, "9876", cfg)
    assert "9876" not in result.reason


# ============================================================================
# EMAIL
# ============================================================================


@pytest.mark.parametrize("value", ["rahul@example.com", "a.b+c@sub.example.co.in"])
def test_email_valid(cfg, value):
    assert _validate(FieldType.EMAIL, value, cfg).is_valid


@pytest.mark.parametrize("value", ["rahul@", "rahul.example.com", "rahul @example.com"])
def test_email_invalid(cfg, value):
    assert not _validate(FieldType.EMAIL, value, cfg).is_valid


def test_email_domain_lowercased(cfg):
    result = _validate(FieldType.EMAIL, "Rahul@EXAMPLE.COM", cfg)
    assert result.normalized == "Rahul@example.com"


# ============================================================================
# AMOUNT
# ============================================================================


@pytest.mark.parametrize("value", ["25000", "Rs. 25,000", "INR 25,000", "₹50,000"])
def test_amount_valid(cfg, value):
    assert _validate(FieldType.AMOUNT, value, cfg).is_valid


@pytest.mark.parametrize("value", ["abc", "₹", "-500", "0"])
def test_amount_invalid(cfg, value):
    assert not _validate(FieldType.AMOUNT, value, cfg).is_valid


# ============================================================================
# DATE
# ============================================================================


@pytest.mark.parametrize("value", ["10/08/2026", "2026-08-10", "10 Aug 2026"])
def test_date_valid(cfg, value):
    result = _validate(FieldType.DATE, value, cfg)
    assert result.is_valid
    assert result.normalized == "2026-08-10"


@pytest.mark.parametrize("value", ["32/13/2026", "tomorrow"])
def test_date_invalid(cfg, value):
    assert not _validate(FieldType.DATE, value, cfg).is_valid


# ============================================================================
# NAME
# ============================================================================


@pytest.mark.parametrize("value", ["Rahul Sharma", "Amit Kumar", "O'Brien", "Priya Devi"])
def test_name_valid(cfg, value):
    assert _validate(FieldType.NAME, value, cfg).is_valid


@pytest.mark.parametrize("value", ["12345", "-", "@#$", "98765432109876"])
def test_name_invalid(cfg, value):
    assert not _validate(FieldType.NAME, value, cfg).is_valid


def test_name_title_cased(cfg):
    result = _validate(FieldType.NAME, "rahul sharma", cfg)
    assert result.normalized == "Rahul Sharma"


# ============================================================================
# NUMBER
# ============================================================================


@pytest.mark.parametrize("value", ["5", "12", "1,234"])
def test_number_valid(cfg, value):
    assert _validate(FieldType.NUMBER, value, cfg).is_valid


@pytest.mark.parametrize("value", ["abc", ""])
def test_number_invalid(cfg, value):
    assert not _validate(FieldType.NUMBER, value, cfg).is_valid


# ============================================================================
# PERCENTAGE
# ============================================================================


@pytest.mark.parametrize("value", ["25", "50%", "100"])
def test_percentage_valid(cfg, value):
    assert _validate(FieldType.PERCENTAGE, value, cfg).is_valid


@pytest.mark.parametrize("value", ["150%", "abc%"])
def test_percentage_invalid(cfg, value):
    assert not _validate(FieldType.PERCENTAGE, value, cfg).is_valid


# ============================================================================
# YES_NO
# ============================================================================


@pytest.mark.parametrize("value", ["Yes", "no", "Y", "TRUE"])
def test_yes_no_valid(cfg, value):
    assert _validate(FieldType.YES_NO, value, cfg).is_valid


@pytest.mark.parametrize("value", ["maybe", "possibly"])
def test_yes_no_invalid(cfg, value):
    assert not _validate(FieldType.YES_NO, value, cfg).is_valid


# ============================================================================
# CHAINAGE
# ============================================================================


@pytest.mark.parametrize("value", ["km 12+300", "12+300", "14.5"])
def test_chainage_valid(cfg, value):
    assert _validate(FieldType.CHAINAGE, value, cfg).is_valid


@pytest.mark.parametrize("value", ["abc", ""])
def test_chainage_invalid(cfg, value):
    assert not _validate(FieldType.CHAINAGE, value, cfg).is_valid


# ============================================================================
# COORDINATE
# ============================================================================


@pytest.mark.parametrize("value", ["17.3850, 78.4867", "-17.385,78.4867"])
def test_coordinate_valid(cfg, value):
    assert _validate(FieldType.COORDINATE, value, cfg).is_valid


@pytest.mark.parametrize("value", ["17.3850", "200, 300"])
def test_coordinate_invalid(cfg, value):
    assert not _validate(FieldType.COORDINATE, value, cfg).is_valid


# ============================================================================
# ADDRESS / LOCATION
# ============================================================================


@pytest.mark.parametrize("field_type", [FieldType.ADDRESS, FieldType.LOCATION])
@pytest.mark.parametrize("value", ["H.No 12-3, Main Road, Nellore", "Village Kotturu"])
def test_address_location_valid(cfg, field_type, value):
    assert _validate(field_type, value, cfg).is_valid


@pytest.mark.parametrize("field_type", [FieldType.ADDRESS, FieldType.LOCATION])
@pytest.mark.parametrize("value", ["-", "12"])
def test_address_location_invalid(cfg, field_type, value):
    assert not _validate(field_type, value, cfg).is_valid


# ============================================================================
# DOCUMENT_REFERENCE
# ============================================================================


@pytest.mark.parametrize("value", ["NH-16/2024/ROW-01", "REF-001"])
def test_document_reference_valid(cfg, value):
    assert _validate(FieldType.DOCUMENT_REFERENCE, value, cfg).is_valid


@pytest.mark.parametrize("value", ["-", "a"])
def test_document_reference_invalid(cfg, value):
    assert not _validate(FieldType.DOCUMENT_REFERENCE, value, cfg).is_valid


# ============================================================================
# TEXT / UNKNOWN -- never invalid on format
# ============================================================================


@pytest.mark.parametrize("field_type", [FieldType.TEXT, FieldType.UNKNOWN])
@pytest.mark.parametrize("value", ["Some remark", "!!!weird but non-empty###"])
def test_text_unknown_always_valid_if_nonempty(cfg, field_type, value):
    assert _validate(field_type, value, cfg).is_valid


@pytest.mark.parametrize("field_type", [FieldType.TEXT, FieldType.UNKNOWN])
def test_text_unknown_invalid_when_empty(cfg, field_type):
    assert not _validate(field_type, "   ", cfg).is_valid


# ============================================================================
# Cross-cutting
# ============================================================================


def test_every_registered_validator_never_raises(cfg):
    weird_inputs = ["", " ", "\n", "😀", "a" * 200, "NULL", "undefined", "0" * 50]
    for field_type in FieldType:
        validator = get_type_profile(field_type).validator
        for value in weird_inputs:
            result = validator(value, cfg)
            assert result.__class__.__name__ == "ValueVerdict"
