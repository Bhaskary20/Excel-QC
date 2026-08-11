"""Phase 5 gate: the 5 worked examples from BUILD_PLAN.md Phase 5, plus a
broader sweep across every registered type."""

import pytest

import app.validators  # noqa: F401 -- sample-value sniffing needs real validators
from app.config import load_config
from app.excel_reader import CellRecord
from app.field_type_detector import detect_field_type
from app.models import FieldType


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _cell(number_format="General", data_validation=None, text="") -> CellRecord:
    return CellRecord(
        sheet="Sheet1",
        cell="A1",
        row=1,
        col=1,
        raw_value=text or None,
        text=text,
        is_merged=False,
        merge_anchor=None,
        number_format=number_format,
        is_bold=False,
        has_comment=False,
        comment_text=None,
        data_validation=data_validation,
    )


# ============================================================================
# The 5 Done-when examples, verbatim
# ============================================================================


def test_contact_numbers_is_phone_with_high_confidence(cfg):
    field_type, confidence = detect_field_type("Contact Numbers", "", None, cfg)
    assert field_type == FieldType.PHONE
    assert confidence >= 0.7


def test_compensation_amount_is_amount_with_high_confidence(cfg):
    field_type, confidence = detect_field_type("Compensation Amount (₹)", "", None, cfg)
    assert field_type == FieldType.AMOUNT
    assert confidence >= 0.7


def test_remarks_is_text(cfg):
    field_type, _ = detect_field_type("Remarks", "", None, cfg)
    assert field_type == FieldType.TEXT


def test_nonsense_label_is_unknown_zero_confidence(cfg):
    field_type, confidence = detect_field_type("Xyzzy", "", None, cfg)
    assert field_type == FieldType.UNKNOWN
    assert confidence == 0.0


def test_currency_number_format_plus_generic_label_is_amount(cfg):
    cell = _cell(number_format="₹#,##0")
    field_type, _ = detect_field_type("Value", "", cell, cfg)
    assert field_type == FieldType.AMOUNT


# ============================================================================
# Broader sweep
# ============================================================================


@pytest.mark.parametrize(
    "label,expected_type",
    [
        ("Phone Number", FieldType.PHONE),
        ("Mobile No.", FieldType.PHONE),
        ("Email ID", FieldType.EMAIL),
        ("Date of Award", FieldType.DATE),
        ("Project Name", FieldType.NAME),
        ("Owner Name", FieldType.NAME),
        ("Address", FieldType.ADDRESS),
        ("Village / Location", FieldType.LOCATION),
        ("Percentage Complete", FieldType.PERCENTAGE),
        ("Chainage (km)", FieldType.CHAINAGE),
        ("GPS Coordinates", FieldType.COORDINATE),
        ("Reference No.", FieldType.DOCUMENT_REFERENCE),
    ],
)
def test_label_sweep(cfg, label, expected_type):
    field_type, confidence = detect_field_type(label, "", None, cfg)
    assert field_type == expected_type
    assert confidence > 0.0


def test_date_number_format_detected(cfg):
    cell = _cell(number_format="dd/mm/yyyy")
    field_type, _ = detect_field_type("Date", "", cell, cfg)
    assert field_type == FieldType.DATE


def test_percentage_number_format_detected(cfg):
    cell = _cell(number_format="0.00%")
    field_type, _ = detect_field_type("Complete", "", cell, cfg)
    assert field_type == FieldType.PERCENTAGE


def test_yes_no_data_validation_detected(cfg):
    cell = _cell(data_validation='"Yes,No"')
    field_type, _ = detect_field_type("Available", "", cell, cfg)
    assert field_type == FieldType.YES_NO


def test_context_alone_can_resolve_an_otherwise_unknown_label(cfg):
    # "Xyzzy" carries no type signal by itself (see the nonsense-label test
    # above); on-topic context text should still be enough to resolve it.
    field_type, confidence = detect_field_type(
        "Xyzzy", "Please provide the contact phone number here", None, cfg
    )
    assert field_type == FieldType.PHONE
    assert confidence > 0.0


def test_score_sample_value_adds_weight_to_matching_types(cfg):
    from collections import defaultdict

    from app.field_type_detector import _score_sample_value

    scores = defaultdict(float)
    cell = _cell(text="rahul@example.com")
    _score_sample_value(cell, "Field", cfg, scores)
    assert scores[FieldType.EMAIL] > 0


def test_score_sample_value_skips_when_sample_equals_label(cfg):
    from collections import defaultdict

    from app.field_type_detector import _score_sample_value

    scores = defaultdict(float)
    cell = _cell(text="Remarks")
    _score_sample_value(cell, "Remarks", cfg, scores)
    assert scores == {}


def test_empty_label_and_context_is_unknown(cfg):
    field_type, confidence = detect_field_type("", "", None, cfg)
    assert field_type == FieldType.UNKNOWN
    assert confidence == 0.0


def test_genuinely_ambiguous_label_falls_back_to_text_not_a_guess(cfg):
    # "Email Address" scores EMAIL (via "email") and ADDRESS (via "address")
    # equally -- a real ambiguity English creates by overloading "address".
    # Guessing between them is exactly what the deterministic layer must not
    # do (that's Phase 15's job); it should concede to TEXT at low confidence.
    field_type, confidence = detect_field_type("Email Address", "", None, cfg)
    assert field_type == FieldType.TEXT
    assert confidence <= 0.5
