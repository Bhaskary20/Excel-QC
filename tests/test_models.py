"""Phase 2 gate: the domain model imports cleanly and TYPE_REGISTRY is complete.

Per-type behavior (separators, validators, keyword scoring) is exercised by
test_value_splitter.py, test_validators.py, and test_field_type_detector.py
once those modules exist (Phases 3-5). This file only checks the shape of
the registry itself, so it's stable across all later phases.
"""

from app.config import load_config
from app.models import (
    TYPE_REGISTRY,
    ExpectedCount,
    CountSource,
    FieldType,
    ParsedValue,
    Status,
    TypeProfile,
    ValueVerdict,
    get_type_profile,
)


def test_every_field_type_has_a_registry_entry():
    missing = [t for t in FieldType if t not in TYPE_REGISTRY]
    assert not missing, f"FieldType members missing from TYPE_REGISTRY: {missing}"


def test_registry_entries_are_well_formed():
    for field_type, profile in TYPE_REGISTRY.items():
        assert isinstance(profile, TypeProfile)
        assert profile.type == field_type
        for sep in profile.allowed_separators:
            assert sep not in profile.forbidden_separators, (
                f"{field_type}: '{sep}' is both allowed and forbidden"
            )
        assert callable(profile.validator)


def test_unknown_type_is_conservative():
    profile = get_type_profile(FieldType.UNKNOWN)
    assert "," in profile.forbidden_separators
    assert profile.label_keywords == []


def test_get_type_profile_falls_back_safely():
    # Every real FieldType member must resolve to itself, never silently to UNKNOWN.
    for field_type in FieldType:
        assert get_type_profile(field_type).type == field_type


def test_placeholder_validator_accepts_nonempty_rejects_empty():
    cfg = load_config()
    profile = get_type_profile(FieldType.PHONE)
    ok = profile.validator("9876543210", cfg)
    assert ok.is_valid is True

    blank = profile.validator("   ", cfg)
    assert blank.is_valid is False


def test_expected_count_defaults_to_exact_bound():
    ec = ExpectedCount(count=10, source=CountSource.EXPLICIT_INSTRUCTION, confidence=0.95)
    assert ec.bound == "exact"


def test_expected_count_unknown_shape():
    ec = ExpectedCount(count=None, source=CountSource.UNKNOWN, confidence=0.20, evidence="no quantity signal found")
    assert ec.count is None
    assert ec.confidence == 0.20


def test_parsed_value_holds_a_verdict():
    pv = ParsedValue(index=1, raw="9876543210", verdict=ValueVerdict(is_valid=True, normalized="9876543210"))
    assert pv.verdict.is_valid
    assert pv.index == 1


def test_status_members_match_spec():
    names = {s.value for s in Status}
    assert names == {"COMPLETE", "PARTIAL", "MISSING", "INVALID", "REVIEW", "NOT_APPLICABLE"}
