"""One response cell's text -> {slot number: raw value}, per BUILD_PLAN.md
v2 Section 4. The highest-risk module in the project: an untouched
scaffold cell must parse as *zero* values, not six, or a blank submission
scores 100%.

Algorithm, in order:
  1. Normalize (NBSP, zero-width chars, line endings, outer whitespace).
  2. Whole-cell N/A check -> is_na.
  3. Fast-path scaffold check: text is byte-identical to the column's
     scaffold_raw (from template_spec) -> is_unfilled_scaffold, no further
     parsing needed.
  4. Numbered parse: markers like "1." "1)" "(1)" "1 . ", found anywhere a
     digit is preceded by string/line start or a space/comma/semicolon (not
     just line start -- "1. A, 2. B" on one line must still split).
  5. If fewer than 2 markers found, positional fallback: split on newline,
     then ;, then type-permitted , or / (comma uses the same digit-guard as
     v1 -- a comma between two digits is a thousands separator).
  6. Per-slot cleanup: strip quotes/trailing punctuation, drop pure
     punctuation, and drop any slot whose cleaned value still equals the
     column's own placeholder text for that slot (the slow-path scaffold
     check, for cells that are *mostly* untouched).
  7. Cap at MAX_SLOTS; note if truncated.

Placeholder comparison (step 6) parses the column's scaffold_raw through
this same numbered-parse logic rather than using a hand-extracted
"placeholder string" -- so both sides of the comparison come from one
algorithm instead of two copies that could drift apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from app.config import Config
from app.template_spec import ColumnSpec, ValueType, get_column

MAX_SLOTS = 50

_NBSP = "\u00a0"
_ZERO_WIDTH_PATTERN = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_MULTI_BLANK_LINES = re.compile(r"\n{3,}")

# Matches a slot marker either at the start of the string/line, or
# immediately after whitespace/comma/semicolon -- so "1. A, 2. B" on one
# physical line still finds marker 2 even though re.MULTILINE's ^ alone
# would only anchor at true line starts.
_SLOT_MARKER_PATTERN = re.compile(
    r"(?:^|(?<=[\s,;]))(?:\((\d{1,2})\)|(\d{1,2})\s*[.\)\-:])\s*",
    re.MULTILINE,
)

_SEPARATOR_PRECEDENCE = ["\n", ";", ",", "/"]
_ALLOWED_SEPARATORS: dict[ValueType, frozenset[str]] = {
    ValueType.PHONE: frozenset({"\n", ";", ",", "/"}),
    ValueType.NAME: frozenset({"\n", ";", ","}),
    ValueType.TEXT: frozenset({"\n", ";"}),
    ValueType.ADDRESS: frozenset({"\n", ";"}),  # commas are structural to an address
    ValueType.NUMBER: frozenset({"\n", ";", ","}),
    ValueType.INTEGER: frozenset({"\n", ";", ","}),
    ValueType.ENUM: frozenset({"\n", ";", ","}),
    ValueType.DATE_RANGE: frozenset({"\n", ";"}),  # "/" and internal "," belong to the date itself
    ValueType.COMPOSITE_LOCATION: frozenset({"\n", ";"}),  # commas are structural (village, city, ...)
}

# Column H is typed TEXT for validation (any non-empty string), but
# functionally it's a list of company names, not prose -- unlike N/P
# (consultant name+address, HTMS/Toll Expert), which read more like
# free text where a comma is more likely structural. Override by column
# letter rather than loosening TEXT globally.
_COLUMN_SEPARATOR_OVERRIDES: dict[str, frozenset[str]] = {
    "H": frozenset({"\n", ";", ","}),
}


def _allowed_separators_for(spec: ColumnSpec) -> frozenset[str]:
    override = _COLUMN_SEPARATOR_OVERRIDES.get(spec.letter)
    if override is not None:
        return override
    return _ALLOWED_SEPARATORS.get(spec.value_type, frozenset({"\n", ";"}))


_DIGIT_INTERNAL_COMMA_SPLIT = re.compile(r"(?<!\d),|,(?!\d)")
_LEADING_QUOTES = re.compile(r"""^['"]+""")
_TRAILING_QUOTES = re.compile(r"""['"]+$""")
_TRAILING_SEPARATOR_CHARS = re.compile(r"[,;.]+$")
_PURE_PUNCTUATION = re.compile(r"^\W+$")


@dataclass(frozen=True)
class SlotParseResult:
    is_na: bool
    is_unfilled_scaffold: bool
    slots: dict[int, str] = field(default_factory=dict)
    note: str = ""


def _normalize(text: Optional[str]) -> str:
    if text is None:
        return ""
    text = text.replace(_NBSP, " ")
    text = _ZERO_WIDTH_PATTERN.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _MULTI_BLANK_LINES.sub("\n\n", text)
    return text.strip()


def _is_na_token(text: str, cfg: Config) -> bool:
    na_tokens = {t.lower() for t in cfg.status.na_tokens}
    return text.strip().lower() in na_tokens


def _clean_slot_value(raw: str) -> str:
    text = raw.strip()
    text = _LEADING_QUOTES.sub("", text)
    text = _TRAILING_QUOTES.sub("", text)
    text = text.strip()
    text = _TRAILING_SEPARATOR_CHARS.sub("", text)
    return text.strip()


def _numbered_parse(text: str) -> dict[int, str]:
    matches = list(_SLOT_MARKER_PATTERN.finditer(text))

    if len(matches) < 2:
        # A lone "1." is still trustworthy -- "only one value, but numbered
        # anyway" is the common case for a single-contract row. A lone
        # marker for any OTHER number is too easily confused with ordinary
        # text ("3-BHK apartment") to trust without a second marker to
        # corroborate it.
        if len(matches) == 1:
            m = matches[0]
            if int(m.group(1) or m.group(2)) == 1:
                content = text[m.end():].strip()
                return {1: content} if content else {}
        return {}

    slots: dict[int, str] = {}
    for i, m in enumerate(matches):
        slot_num = int(m.group(1) or m.group(2))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        slots[slot_num] = text[start:end]
    return slots


def _split_on(text: str, sep: str) -> list[str]:
    if sep == ",":
        return _DIGIT_INTERNAL_COMMA_SPLIT.split(text)
    return text.split(sep)


def _positional_fallback(text: str, spec: ColumnSpec) -> dict[int, str]:
    allowed = _allowed_separators_for(spec)

    for sep in _SEPARATOR_PRECEDENCE:
        if sep not in allowed:
            continue
        parts = _split_on(text, sep)
        cleaned = [p.strip() for p in parts if p.strip()]
        if len(cleaned) >= 2:
            return {i: v for i, v in enumerate(cleaned, start=1)}

    stripped = text.strip()
    return {1: stripped} if stripped else {}


@lru_cache(maxsize=None)
def _placeholder_slots_for_column(column_letter: str) -> dict[int, str]:
    spec = get_column(column_letter)
    if spec.scaffold_raw is None:
        return {}
    return {slot: _clean_slot_value(raw) for slot, raw in _numbered_parse(spec.scaffold_raw).items()}


def _parse_slotted_cell(normalized: str, spec: ColumnSpec) -> SlotParseResult:
    if spec.scaffold_raw is not None and normalized == spec.scaffold_raw.strip():
        return SlotParseResult(is_na=False, is_unfilled_scaffold=True)

    raw_slots = _numbered_parse(normalized)
    if not raw_slots:
        raw_slots = _positional_fallback(normalized, spec)

    cleaned_slots: dict[int, str] = {}
    for slot_num, raw_value in raw_slots.items():
        if slot_num > MAX_SLOTS:
            continue
        cleaned = _clean_slot_value(raw_value)
        if not cleaned or _PURE_PUNCTUATION.match(cleaned):
            continue
        cleaned_slots[slot_num] = cleaned

    placeholders = _placeholder_slots_for_column(spec.letter)
    if placeholders:
        cleaned_slots = {
            slot: value
            for slot, value in cleaned_slots.items()
            if placeholders.get(slot) != value
        }

    note = ""
    if len(raw_slots) > MAX_SLOTS:
        note = f"truncated at {MAX_SLOTS} slots"

    if not cleaned_slots:
        return SlotParseResult(is_na=False, is_unfilled_scaffold=True, note=note)

    return SlotParseResult(is_na=False, is_unfilled_scaffold=False, slots=cleaned_slots, note=note)


def parse_slots(text: Optional[str], column_letter: str, cfg: Config) -> SlotParseResult:
    spec = get_column(column_letter)
    normalized = _normalize(text)

    if not normalized:
        return SlotParseResult(is_na=False, is_unfilled_scaffold=True)

    if _is_na_token(normalized, cfg):
        return SlotParseResult(is_na=True, is_unfilled_scaffold=False)

    if not spec.slotted:
        cleaned = _clean_slot_value(normalized)
        if not cleaned or _PURE_PUNCTUATION.match(cleaned):
            return SlotParseResult(is_na=False, is_unfilled_scaffold=True)
        return SlotParseResult(is_na=False, is_unfilled_scaffold=False, slots={1: cleaned})

    return _parse_slotted_cell(normalized, spec)
