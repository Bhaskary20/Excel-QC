"""Per-column-type validators, per BUILD_PLAN.md v2 Section 3.

At the user's request, most content/format validation has been removed:
for the 8 "core" columns (H, I, J, K, L, M, Q, R) and for N/O/P, only
whether a slot has *something* in it matters, never what that something
looks like -- a malformed date, a typo'd enum value, a garbled phone
number are all still "an answer", not a missing one. What still counts a
slot as unanswered (blank, or a recognized non-answer phrase like "NA" /
"Not Assigned" / "Nil") is decided upstream in slot_parser.py before a
value ever reaches a validator here -- so validate_present below never
even sees those cases. Only F (village/location, still just a soft
"warn") and G (Plaza Type, a real fixed vocabulary) still validate actual
content, since neither is part of the 8 quantity-only columns or the
N/O/P group.

Every validator takes (value, cfg, spec) even where unused, so
VALIDATOR_REGISTRY can dispatch on ValueType alone without a column-letter
branch (see models.py).

Importing this module is what activates real validation -- until then,
VALIDATOR_REGISTRY entries carry the models.py placeholder that accepts any
non-empty value (see Phases B/C's tests, which run before this module
exists).

Rules every validator follows:
  - Never raises. Malformed input is INVALID, not an exception.
  - `reason` describes the value's *shape*, never echoes the raw value --
    reason strings land directly in QC_Report.xlsx (Sheet: Slot Analysis).
"""

from __future__ import annotations

import re

from app.config import Config
from app.models import VALIDATOR_REGISTRY, ValueVerdict
from app.template_spec import ColumnSpec, ValueType


def _ok(normalized: str, reason: str = "") -> ValueVerdict:
    return ValueVerdict(is_valid=True, normalized=normalized, reason=reason)


def _fail(reason: str) -> ValueVerdict:
    return ValueVerdict(is_valid=False, normalized=None, reason=reason)


_HAS_LETTER = re.compile(r"[^\W\d_]")


# ============================================================================
# INTEGER -- registered for completeness; A (S.No) is a KEY column and is
# never actually run through this (KEY columns aren't graded).
# ============================================================================


def validate_integer(value: str, cfg: Config, spec: ColumnSpec) -> ValueVerdict:
    text = value.strip().replace(",", "")
    if not re.fullmatch(r"-?\d+", text):
        return _fail("not a valid integer")
    return _ok(str(int(text)))


# ============================================================================
# Presence-only validator -- H, I, J, K, L, M, N, O, P, Q, R, S all resolve
# here (TEXT, NAME, PHONE, DATE_RANGE, ADDRESS, NUMBER value types). Content
# is never checked; a slot reaching this point has already survived
# slot_parser.py's blank/NA/pure-punctuation filtering upstream, so it's
# accepted as-is.
# ============================================================================


def validate_present(value: str, cfg: Config, spec: ColumnSpec) -> ValueVerdict:
    return _ok(value.strip())


# ============================================================================
# COMPOSITE_LOCATION -- F only. "warn" (still valid) below 4 components or
# missing pincode; genuinely invalid only when there's no letter at all.
# ============================================================================

_PINCODE_PATTERN = re.compile(r"\b\d{6}\b")


def validate_composite_location(value: str, cfg: Config, spec: ColumnSpec) -> ValueVerdict:
    text = value.strip()
    if not _HAS_LETTER.search(text):
        return _fail("contains no letters")

    components = [c.strip() for c in re.split(r"[,+]", text) if c.strip()]
    has_pincode = bool(_PINCODE_PATTERN.search(text))

    warnings = []
    expected = len(spec.composite_components) or 4
    if len(components) < expected:
        warnings.append(f"expected {expected} components (village, chainage, city, pincode), found {len(components)}")
    if not has_pincode:
        warnings.append("no 6-digit pincode found")

    return _ok(text, reason="; ".join(warnings))


# ============================================================================
# ENUM -- G (Plaza Type) and I (EQ/Regular) share this, disambiguated by
# spec.enum_values / spec.enum_aliases.
# ============================================================================

_ENUM_NORMALIZE_PATTERN = re.compile(r"[\s\-_/]+")


def _normalize_enum_text(text: str) -> str:
    return _ENUM_NORMALIZE_PATTERN.sub(" ", text.strip()).strip().casefold()


def validate_enum(value: str, cfg: Config, spec: ColumnSpec) -> ValueVerdict:
    if not spec.enum_values:
        return _fail("no enum values configured for this column")

    text = value.strip()
    key = _normalize_enum_text(text)
    normalized_map = {_normalize_enum_text(v): v for v in spec.enum_values}

    if key in normalized_map:
        return _ok(normalized_map[key])

    for canonical, aliases in spec.enum_aliases.items():
        for alias in aliases:
            if _normalize_enum_text(alias) in key:
                return _ok(canonical)

    options = ", ".join(spec.enum_values)
    return _fail(f"not one of: {options}")


# ============================================================================
# Registration -- the only place that maps ValueType -> validator function
# ============================================================================


def register_validators() -> None:
    VALIDATOR_REGISTRY[ValueType.INTEGER] = validate_integer
    VALIDATOR_REGISTRY[ValueType.TEXT] = validate_present
    VALIDATOR_REGISTRY[ValueType.COMPOSITE_LOCATION] = validate_composite_location
    VALIDATOR_REGISTRY[ValueType.ENUM] = validate_enum
    VALIDATOR_REGISTRY[ValueType.NAME] = validate_present
    VALIDATOR_REGISTRY[ValueType.PHONE] = validate_present
    VALIDATOR_REGISTRY[ValueType.DATE_RANGE] = validate_present
    VALIDATOR_REGISTRY[ValueType.ADDRESS] = validate_present
    VALIDATOR_REGISTRY[ValueType.NUMBER] = validate_present


register_validators()
