"""One cell's text -> value tokens, type-aware.

The central problem this module solves: a cell can hold either a single
logical value ("H.No 12-3, Main Road, Nellore", "10/08/2026", "₹2,50,000")
or a list of them ("9876543210, 9876543211, 9876543212"), and the same
punctuation (comma, slash) means different things in each case. Splitting
must be driven by the field's expected type, not by blind punctuation
matching -- see BUILD_PLAN.md Phase 3 for the full worked-example table.

Algorithm, in order:
  1. Early exits: blank text -> [], an N/A-ish token -> [NA_SENTINEL].
  2. Try separators in precedence order (newline > ; > | > , > /), but only
     ones the field type actually allows (TYPE_REGISTRY[type].allowed_separators).
     The first one that yields >= 2 non-empty cleaned tokens wins.
  3. Comma is special-cased everywhere: a comma is only treated as a value
     separator when it is not sitting directly between two digits, so
     "₹2,50,000" (thousands grouping) never gets exploded while
     "₹2,50,000, ₹3,00,000" (two grouped amounts) splits into two. This
     already generalizes correctly for every type that allows comma --
     types where a comma is structural to the value itself (ADDRESS,
     LOCATION, COORDINATE, TEXT) simply don't list "," as an allowed
     separator in the first place, so it's never attempted for them.
  4. Each token is cleaned: enumeration markers ("1.", "(a)", bullets)
     stripped, surrounding quotes/whitespace trimmed, trailing separator
     punctuation removed, and anything left empty or pure punctuation is
     dropped.
  5. If nothing produced >= 2 tokens, the whole cleaned text is returned as
     a single value (Step 7's "single-value fallback").
"""

from __future__ import annotations

import re
from typing import Optional

from app.config import Config
from app.models import FieldType, TypeProfile, get_type_profile

NA_SENTINEL = "__NA__"

# Precedence order: strongest, least ambiguous separator first. A cell that
# mixes separators (e.g. newline-joined values with stray trailing commas)
# splits on the winning separator only -- the loser's characters get cleaned
# up per-token in Step 4, not used for a second split pass.
_SEPARATOR_PRECEDENCE = ["\n", ";", "|", ",", "/"]

# Matches a comma that sits directly between two digits ("2,50,000"), i.e. a
# thousands-grouping comma rather than a value separator. Splitting on the
# complement of this (see _split_on) is what lets "₹2,50,000" stay whole
# while "₹2,50,000, ₹3,00,000" splits into two -- the same regex handles
# both cases because a text with only grouping commas simply produces zero
# split points.
_DIGIT_INTERNAL_COMMA_SPLIT = re.compile(r"(?<!\d),|,(?!\d)")

_ENUMERATION_PATTERN = re.compile(
    r"^\s*(\(?\d{1,3}[\.\)\-:]|\d{1,3}\s*[\.\)]|[•·▪\-*]|\(?[a-zA-Z][\.\)]|\(?[ivxIVX]+[\.\)])\s+"
)
_LEADING_QUOTES = re.compile(r"""^['"]+""")
_TRAILING_QUOTES = re.compile(r"""['"]+$""")
_TRAILING_SEPARATOR_CHARS = re.compile(r"[,;.]+$")
_PURE_PUNCTUATION = re.compile(r"^\W+$")


def strip_enumeration(token: str) -> str:
    """Remove a leading enumeration marker ("1.", "(a)", "iv)", a bullet),
    but only if something remains afterward -- a bare "5" or a decimal like
    "1.5" never matches because the pattern requires whitespace *and* more
    content after the marker, so numeric values are never misread as
    numbering."""
    stripped = _ENUMERATION_PATTERN.sub("", token, count=1).strip()
    return stripped if stripped else token.strip()


def _clean_token(token: str) -> str:
    token = strip_enumeration(token)
    token = _LEADING_QUOTES.sub("", token)
    token = _TRAILING_QUOTES.sub("", token)
    token = token.strip()
    token = _TRAILING_SEPARATOR_CHARS.sub("", token)
    return token.strip()


def _split_on(text: str, sep: str) -> list[str]:
    if sep == ",":
        return _DIGIT_INTERNAL_COMMA_SPLIT.split(text)
    return text.split(sep)


def _count_nonempty_cleaned(parts: list[str]) -> int:
    return sum(1 for p in parts if _clean_token(p))


def detect_separator(text: str, profile: TypeProfile) -> Optional[str]:
    """First separator (in precedence order) that the type allows and that
    yields >= 2 non-empty cleaned tokens. None means: treat as one value."""
    for sep in _SEPARATOR_PRECEDENCE:
        if sep not in profile.allowed_separators:
            continue
        parts = _split_on(text, sep)
        if _count_nonempty_cleaned(parts) >= 2:
            return sep
    return None


def split_values(text: Optional[str], field_type: FieldType, cfg: Config) -> list[str]:
    if text is None:
        return []
    stripped = text.strip()
    if not stripped:
        return []

    na_tokens = {t.lower() for t in cfg.status.na_tokens}
    if stripped.lower() in na_tokens:
        return [NA_SENTINEL]

    profile = get_type_profile(field_type)
    sep = detect_separator(stripped, profile)

    if sep is None:
        cleaned = _clean_token(stripped)
        tokens = [cleaned] if cleaned else []
    else:
        parts = _split_on(stripped, sep)
        tokens = [_clean_token(p) for p in parts]
        tokens = [t for t in tokens if t and not _PURE_PUNCTUATION.match(t)]

    if len(tokens) > cfg.parsing.max_values_per_cell:
        tokens = tokens[: cfg.parsing.max_values_per_cell]

    return tokens
