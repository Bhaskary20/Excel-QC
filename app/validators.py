"""Per-column-type validators, per BUILD_PLAN.md v2 Section 3.

Every validator takes (value, cfg, spec) -- see models.py for why spec is
required even where unused: G and I are both ENUM but have different valid
value sets; H/N/P/S are all TEXT but S (optional) is far more permissive
than the other three. Reading spec.enum_values / spec.required at call time
lets one generic validator per ValueType handle this instead of needing a
column-letter branch.

Importing this module is what activates real validation -- until then,
VALIDATOR_REGISTRY entries carry the models.py placeholder that accepts any
non-empty value (see Phases B/C's tests, which run before this module
exists).

Rules every validator follows:
  - Never raises. Malformed input is INVALID, not an exception.
  - `reason` describes the value's *shape*, never echoes the raw value --
    reason strings land directly in QC_Report.xlsx (Sheet: Slot Analysis).
  - Where BUILD_PLAN.md v2 Section 3 says "warn" rather than "invalid"
    (F's component count, J's contract-window check), the value stays
    valid and the concern goes in `reason` -- qc_engine (Phase G) decides
    whether a non-empty reason on an otherwise-valid value is worth
    surfacing as REVIEW; the validator's job is just to say what it saw.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from app.config import Config
from app.models import VALIDATOR_REGISTRY, ValueVerdict
from app.template_spec import CONTRACT_WINDOW, ColumnSpec, ValueType


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
# TEXT -- H, N, P (required: >=3 chars, contains a letter) and S (optional
# Remarks: any non-empty text). spec.required is what tells them apart.
# ============================================================================


def validate_text(value: str, cfg: Config, spec: ColumnSpec) -> ValueVerdict:
    text = value.strip()

    if not spec.required:
        return _ok(text) if text else _fail("empty value")

    if len(text) < 3:
        return _fail("too short (min 3 characters)")
    if not _HAS_LETTER.search(text):
        return _fail("contains no letters")
    return _ok(text)


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
# NAME -- K, O. Same shape as v1: letters/space/./'/-, Unicode-aware via
# [^\W\d_] so Indian-script names pass without needing the `regex` package.
# "&" and "/" are also allowed directly in the name so two people sharing
# one slot ("Sanjeev Singh/Anil Singh") aren't rejected outright.
#
# Real client data overwhelmingly appends extra info after a real name: a
# role tag in parens ("(RE)", "(TL)", "(ATL)", "(Team Leader)"), a tenure
# date range ("(01.01.2021 to 21.07.2024)"), or a contact detail after a
# comma/dash ("Ravindra Patel, 9111163032", "Sh. Ashok Kumar- info@x.com").
# None of that makes the underlying name itself invalid -- strip it before
# validating rather than rejecting a real name over its annotation. Known
# gap: if the *entire* value is a parenthetical explanation with only a
# short non-name fragment outside it (e.g. "MoRTH (Only Toll collection...)"),
# that fragment can slip through looking like a short but valid name --
# accepted as a disclosed trade-off given how much real annotated data this
# unblocks.
# ============================================================================

_NAME_CHAR_PATTERN = re.compile(r"^[^\W\d_](?:[ .'\-&/]|[^\W\d_])*$")
_DIGIT_CHAR = re.compile(r"\d")
_PAREN_ANNOTATION = re.compile(r"\([^)]*\)?")
# A phone number introduced by its own label ("Mobile: 8817009004", "Mo
# 97855 70801", "Mob- 8874768888, 8318221447") rather than a bare comma/dash.
_TRAILING_LABELED_CONTACT = re.compile(
    r"\s+(?:mobile|mob|mo|contact|phone|ph)\s*[:.\-]?\s*\d[\d\s,]*$", re.IGNORECASE
)
_TRAILING_CONTACT_SUFFIX = re.compile(r"[,\-]\s*(?=[^,\-]*(?:\d|@))[^,\-]*$")
_STRAY_EDGE_PUNCTUATION = re.compile(r"^[\s.,;\-]+|[\s.,;\-]+$")


def _strip_name_annotations(text: str) -> str:
    stripped = _PAREN_ANNOTATION.sub(" ", text)
    stripped = _TRAILING_LABELED_CONTACT.sub("", stripped)
    stripped = _TRAILING_CONTACT_SUFFIX.sub("", stripped)
    stripped = re.sub(r"\s+", " ", stripped)
    return _STRAY_EDGE_PUNCTUATION.sub("", stripped).strip()


def validate_name(value: str, cfg: Config, spec: ColumnSpec) -> ValueVerdict:
    text = re.sub(r"\s+", " ", value.strip())
    core = _strip_name_annotations(text)
    annotation_stripped = core != text

    length = len(core)
    if length < cfg.validation.name.min_length or length > cfg.validation.name.max_length:
        return _fail(f"expected {cfg.validation.name.min_length}-{cfg.validation.name.max_length} characters, got {length}")

    digit_count = len(_DIGIT_CHAR.findall(core))
    if digit_count / length >= 0.8:
        return _fail("mostly digits, not a name")

    if not _NAME_CHAR_PATTERN.match(core):
        return _fail("contains characters not allowed in a name (letters, spaces, . ' - & / only)")

    normalized = " ".join(word.capitalize() for word in core.split(" "))
    reason = "trailing annotation (role tag / contact detail / date range) stripped" if annotation_stripped else ""
    return _ok(normalized, reason=reason)


# ============================================================================
# PHONE -- L only.
# ============================================================================

_PHONE_STRIP_CHARS = re.compile(r"[\s\-()]")
_PHONE_CC_PREFIX = re.compile(r"^(?:\+?91|0091|0)(?=\d{10}$)")


def validate_phone(value: str, cfg: Config, spec: ColumnSpec) -> ValueVerdict:
    cleaned = _PHONE_STRIP_CHARS.sub("", value.strip())
    if cfg.validation.phone.allow_country_code:
        cleaned = _PHONE_CC_PREFIX.sub("", cleaned)

    if not cleaned.isdigit():
        return _fail("contains non-digit characters")

    expected_lengths = cfg.validation.phone.allowed_lengths
    if len(cleaned) not in expected_lengths:
        return _fail(f"expected {expected_lengths[0]} digits, got {len(cleaned)}")

    if cleaned[0] not in cfg.validation.phone.allowed_first_digits:
        return _fail(f"must start with one of {cfg.validation.phone.allowed_first_digits}")

    return _ok(cleaned)


# ============================================================================
# DATE_RANGE -- J only. Scans for date-shaped tokens anywhere in the text
# rather than splitting on a separator, so "10/08/2021 - 14/01/2026",
# "10/08/2021 to 14/01/2026", and the scaffold-echoing
# "From (10/08/2021) - To (14/01/2026)" all parse the same way.
# ============================================================================

_DATE_TOKEN_PATTERN = re.compile(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}")
_DATE_TOKEN_FORMATS = ["%d/%m/%Y", "%d.%m.%Y", "%d/%m/%y", "%d.%m.%y"]


def _parse_date_token(token: str) -> Optional[date]:
    for fmt in _DATE_TOKEN_FORMATS:
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None


def validate_date_range(value: str, cfg: Config, spec: ColumnSpec) -> ValueVerdict:
    text = value.strip()
    tokens = _DATE_TOKEN_PATTERN.findall(text)

    if len(tokens) != 2:
        return _fail(f"expected two dates (start - end), found {len(tokens)}")

    start = _parse_date_token(tokens[0])
    end = _parse_date_token(tokens[1])
    if start is None or end is None:
        return _fail("one or both dates could not be parsed")

    if start > end:
        return _fail("start date is after end date")

    window_start, window_end = CONTRACT_WINDOW
    warning = ""
    if start < window_start or end > window_end:
        warning = f"outside contract window {window_start.isoformat()} to {window_end.isoformat()}"

    return _ok(f"{start.isoformat()}/{end.isoformat()}", reason=warning)


# ============================================================================
# ADDRESS -- M only.
# ============================================================================


def validate_address(value: str, cfg: Config, spec: ColumnSpec) -> ValueVerdict:
    text = value.strip()
    if len(text) < 10:
        return _fail("too short to be a plausible address (min 10 characters)")
    if not _HAS_LETTER.search(text):
        return _fail("contains no letters")
    return _ok(text)


# ============================================================================
# NUMBER -- Q, R (traffic counts). Positive integers after stripping
# grouping commas, known unit words, fiscal-year labels some PIUs attach to
# each yearly figure (e.g. "FY 2020-21 - 1240", "2924.95 (FY 2020-21)"), and
# a trailing parenthetical remark some PIUs append (e.g. "4824 (Till Date
# 27/07/2026)", including one seen missing its closing paren).
# ============================================================================

_NUMBER_UNIT_PATTERN = re.compile(
    r"\b(veh(?:icles?)?|pcu|per\s*avg\.?\s*traffic|per\s*day)\b|/\s*day", re.IGNORECASE
)
_FY_LABEL_PATTERN = re.compile(r"\bFY\s*\d{4}\s*[-–]\s*\d{2,4}\b", re.IGNORECASE)
_TRAILING_PAREN_REMARK = re.compile(r"\([^)]*\)?\s*$")
_NUMBER_TOKEN_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


def validate_number(value: str, cfg: Config, spec: ColumnSpec) -> ValueVerdict:
    text = value.strip().replace(",", "")
    text = _FY_LABEL_PATTERN.sub(" ", text)
    text = _TRAILING_PAREN_REMARK.sub(" ", text)
    text = _NUMBER_UNIT_PATTERN.sub(" ", text).strip()

    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        cleaned = text
    else:
        # After stripping the fiscal-year label and unit words, a single
        # leftover numeric token is unambiguous; anything else (none, or
        # more than one) is a genuinely unparseable value.
        tokens = _NUMBER_TOKEN_PATTERN.findall(text)
        if len(tokens) != 1:
            return _fail("not a valid number")
        cleaned = tokens[0]

    numeric = float(cleaned)
    if numeric < 0:
        return _fail("negative values are not allowed")
    if numeric == 0 and not spec.allow_zero:
        return _fail("must be a positive value")

    normalized = str(int(numeric)) if numeric == int(numeric) else str(numeric)
    return _ok(normalized)


# ============================================================================
# Registration -- the only place that maps ValueType -> validator function
# ============================================================================


def register_validators() -> None:
    VALIDATOR_REGISTRY[ValueType.INTEGER] = validate_integer
    VALIDATOR_REGISTRY[ValueType.TEXT] = validate_text
    VALIDATOR_REGISTRY[ValueType.COMPOSITE_LOCATION] = validate_composite_location
    VALIDATOR_REGISTRY[ValueType.ENUM] = validate_enum
    VALIDATOR_REGISTRY[ValueType.NAME] = validate_name
    VALIDATOR_REGISTRY[ValueType.PHONE] = validate_phone
    VALIDATOR_REGISTRY[ValueType.DATE_RANGE] = validate_date_range
    VALIDATOR_REGISTRY[ValueType.ADDRESS] = validate_address
    VALIDATOR_REGISTRY[ValueType.NUMBER] = validate_number


register_validators()
