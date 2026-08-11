"""Per-type value validators.

Each validator has the signature (value: str, cfg) -> ValueVerdict and is
registered into TYPE_REGISTRY at the bottom of this module, so nothing
outside this file ever branches on FieldType to decide how to validate a
value -- callers always go through TYPE_REGISTRY[field_type].validator.

Importing this module is what activates real validation: until it's
imported somewhere in the process (main.py does this at startup),
TYPE_REGISTRY entries still carry the placeholder from models.py that
accepts any non-empty value. That placeholder is what lets Phases 1-3 be
tested in isolation before this module exists.

Rules every validator follows:
  - Never raises. Malformed input is INVALID, not an exception.
  - `reason` describes the value's *shape*, never echoes the raw value --
    reason strings land directly in QC_Report.xlsx (Sheet 3).
"""

from __future__ import annotations

import re
from datetime import datetime

from dateutil import parser as dateutil_parser

from app.config import Config
from app.models import TYPE_REGISTRY, FieldType, ValueVerdict


def _ok(normalized: str) -> ValueVerdict:
    return ValueVerdict(is_valid=True, normalized=normalized, reason="")


def _fail(reason: str) -> ValueVerdict:
    return ValueVerdict(is_valid=False, normalized=None, reason=reason)


# ============================================================================
# PHONE
# ============================================================================

_PHONE_STRIP_CHARS = re.compile(r"[\s\-()]")
_PHONE_CC_PREFIX = re.compile(r"^(?:\+?91|0091|0)(?=\d{10}$)")


def validate_phone(value: str, cfg: Config) -> ValueVerdict:
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
# EMAIL
# ============================================================================

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def validate_email(value: str, cfg: Config) -> ValueVerdict:
    text = value.strip()
    if not _EMAIL_PATTERN.match(text):
        return _fail("not a valid email shape (expected local@domain.tld)")
    local, _, domain = text.partition("@")
    return _ok(f"{local}@{domain.lower()}")


# ============================================================================
# AMOUNT
# ============================================================================

_AMOUNT_SHAPE = re.compile(r"\d+(\.\d+)?")


def validate_amount(value: str, cfg: Config) -> ValueVerdict:
    text = value.strip()

    is_negative = text.startswith("-")
    if is_negative:
        text = text[1:].strip()

    lowered = text.lower()
    for symbol in cfg.validation.amount.currency_symbols:
        if lowered.startswith(symbol.lower()):
            text = text[len(symbol):].strip()
            lowered = text.lower()
            break

    if cfg.validation.amount.allow_indian_grouping:
        text = text.replace(",", "")

    if not re.fullmatch(r"\d+(\.\d+)?", text):
        return _fail("not a valid amount shape (expected digits, optional currency/grouping)")

    numeric = float(text)

    if is_negative:
        if not cfg.validation.amount.allow_negative:
            return _fail("negative amounts are not allowed")
        numeric = -numeric

    if numeric == 0:
        return _fail("amount must be a positive value")

    normalized = str(int(numeric)) if numeric == int(numeric) else str(numeric)
    return _ok(normalized)


# ============================================================================
# DATE
# ============================================================================


def validate_date(value: str, cfg: Config) -> ValueVerdict:
    text = value.strip()

    for fmt in cfg.validation.date.formats:
        try:
            parsed = datetime.strptime(text, fmt)
            return _ok(parsed.date().isoformat())
        except ValueError:
            continue

    try:
        parsed = dateutil_parser.parse(text, dayfirst=cfg.validation.date.dayfirst)
        return _ok(parsed.date().isoformat())
    except (ValueError, OverflowError, TypeError):
        return _fail("not a recognizable date")


# ============================================================================
# NAME
# ============================================================================

# [^\W\d_] = a "word" character that is neither a digit nor underscore --
# in Python's Unicode-aware re, that's effectively "a letter in any script"
# (covers Telugu/Hindi/etc. names without needing the third-party `regex`
# package; see BUILD_PLAN.md Phase 14 for further hardening if ever needed).
_NAME_CHAR_PATTERN = re.compile(r"^[^\W\d_](?:[ .'\-]|[^\W\d_])*$")
_DIGIT_CHAR = re.compile(r"\d")


def validate_name(value: str, cfg: Config) -> ValueVerdict:
    text = re.sub(r"\s+", " ", value.strip())

    length = len(text)
    if length < cfg.validation.name.min_length or length > cfg.validation.name.max_length:
        return _fail(
            f"expected {cfg.validation.name.min_length}-{cfg.validation.name.max_length} characters, got {length}"
        )

    digit_count = len(_DIGIT_CHAR.findall(text))
    if digit_count / length >= 0.8:
        return _fail("mostly digits, not a name")

    if not _NAME_CHAR_PATTERN.match(text):
        return _fail("contains characters not allowed in a name (letters, spaces, . ' - only)")

    normalized = " ".join(word.capitalize() for word in text.split(" "))
    return _ok(normalized)


# ============================================================================
# NUMBER
# ============================================================================


def validate_number(value: str, cfg: Config) -> ValueVerdict:
    text = value.strip().replace(",", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", text):
        return _fail("not a valid number")
    numeric = float(text)
    normalized = str(int(numeric)) if numeric == int(numeric) else str(numeric)
    return _ok(normalized)


# ============================================================================
# PERCENTAGE
# ============================================================================


def validate_percentage(value: str, cfg: Config) -> ValueVerdict:
    text = value.strip()
    if text.endswith("%"):
        text = text[:-1].strip()

    if not re.fullmatch(r"\d+(\.\d+)?", text):
        return _fail("not a valid percentage shape")

    numeric = float(text)
    if not (0 <= numeric <= 100):
        return _fail(f"expected 0-100, got {numeric}")

    normalized = str(int(numeric)) if numeric == int(numeric) else str(numeric)
    return _ok(f"{normalized}%")


# ============================================================================
# YES_NO
# ============================================================================

_YES_VALUES = {"yes", "y", "true", "✓"}
_NO_VALUES = {"no", "n", "false", "✗"}


def validate_yes_no(value: str, cfg: Config) -> ValueVerdict:
    text = value.strip().lower()
    if text in _YES_VALUES:
        return _ok("YES")
    if text in _NO_VALUES:
        return _ok("NO")
    return _fail("expected yes/no")


# ============================================================================
# CHAINAGE
# ============================================================================

_CHAINAGE_PLUS_FORM = re.compile(r"^(?:km\s*)?\d+\s*\+\s*\d{1,3}$", re.IGNORECASE)
_CHAINAGE_DECIMAL_FORM = re.compile(r"^(?:km\s*)?\d+(?:\.\d+)?\s*(?:km)?$", re.IGNORECASE)


def validate_chainage(value: str, cfg: Config) -> ValueVerdict:
    text = value.strip()

    if _CHAINAGE_PLUS_FORM.match(text) or _CHAINAGE_DECIMAL_FORM.match(text):
        return _ok(text.replace(" ", "").lower())

    return _fail("not a valid chainage (expected 'km 12+300' or a decimal km value)")


# ============================================================================
# COORDINATE
# ============================================================================

# Decimal "lat, lon" pairs only. DMS (17°23'06"N) is a documented gap --
# add it here if a real template ever needs it (see BUILD_PLAN.md Phase 14).
_COORDINATE_PAIR = re.compile(r"^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$")


def validate_coordinate(value: str, cfg: Config) -> ValueVerdict:
    text = value.strip()
    match = _COORDINATE_PAIR.match(text)
    if not match:
        return _fail("expected 'lat, lon' pair")

    lat = float(match.group(1))
    lon = float(match.group(2))

    if not (-90 <= lat <= 90):
        return _fail(f"latitude out of range: {lat}")
    if not (-180 <= lon <= 180):
        return _fail(f"longitude out of range: {lon}")

    return _ok(f"{lat},{lon}")


# ============================================================================
# ADDRESS / LOCATION -- deliberately permissive, same validator for both
# ============================================================================

_HAS_LETTER = re.compile(r"[^\W\d_]")


def validate_address_like(value: str, cfg: Config) -> ValueVerdict:
    text = value.strip()
    if len(text) < 5:
        return _fail("too short to be a plausible address/location (min 5 characters)")
    if not _HAS_LETTER.search(text):
        return _fail("contains no letters")
    return _ok(text)


# ============================================================================
# DOCUMENT_REFERENCE
# ============================================================================

_DOC_REF_ALLOWED = re.compile(r"^[A-Za-z0-9\-/]+$")


def validate_document_reference(value: str, cfg: Config) -> ValueVerdict:
    text = value.strip()
    if len(text) < 3:
        return _fail("too short to be a plausible reference (min 3 characters)")
    if not _DOC_REF_ALLOWED.match(text):
        return _fail("expected alphanumeric characters with - or / only")
    return _ok(text)


# ============================================================================
# TEXT / UNKNOWN -- never invalid on format
# ============================================================================


def validate_text(value: str, cfg: Config) -> ValueVerdict:
    text = value.strip()
    if not text:
        return _fail("empty value")
    return _ok(text)


# ============================================================================
# Registration -- the only place that maps FieldType -> validator function
# ============================================================================


def register_validators() -> None:
    TYPE_REGISTRY[FieldType.PHONE].validator = validate_phone
    TYPE_REGISTRY[FieldType.EMAIL].validator = validate_email
    TYPE_REGISTRY[FieldType.AMOUNT].validator = validate_amount
    TYPE_REGISTRY[FieldType.DATE].validator = validate_date
    TYPE_REGISTRY[FieldType.NAME].validator = validate_name
    TYPE_REGISTRY[FieldType.NUMBER].validator = validate_number
    TYPE_REGISTRY[FieldType.PERCENTAGE].validator = validate_percentage
    TYPE_REGISTRY[FieldType.YES_NO].validator = validate_yes_no
    TYPE_REGISTRY[FieldType.CHAINAGE].validator = validate_chainage
    TYPE_REGISTRY[FieldType.COORDINATE].validator = validate_coordinate
    TYPE_REGISTRY[FieldType.ADDRESS].validator = validate_address_like
    TYPE_REGISTRY[FieldType.LOCATION].validator = validate_address_like
    TYPE_REGISTRY[FieldType.DOCUMENT_REFERENCE].validator = validate_document_reference
    TYPE_REGISTRY[FieldType.TEXT].validator = validate_text
    TYPE_REGISTRY[FieldType.UNKNOWN].validator = validate_text


register_validators()
