"""Label/context -> FieldType, with a confidence score.

No field type is ever hardcoded here as a special case -- every type in
TYPE_REGISTRY is scored the same way, using metadata already sitting on its
TypeProfile (label_keywords, label_patterns). Adding a new FieldType to
models.py makes it participate in detection automatically.

Evidence, in descending weight (see BUILD_PLAN.md Phase 5):
  1. Number format on the cell            (0.9)
  2. Data validation rule on the cell     (0.85)
  3. Label regex pattern match            (0.8)
  4. Label keyword substring match        (0.6)
  5. Same two checks against context text (0.7x their normal weight)
  6. Sample value in the cell validates against a type's validator (0.5)

Scores accumulate per type (at most one hit per evidence tier per type, via
the `break` after each match), then confidence = top / (top + runner-up).
A tie (or near-tie) below 0.5 falls back to TEXT rather than guessing.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from app.config import Config
from app.excel_reader import CellRecord
from app.models import TYPE_REGISTRY, FieldType, get_type_profile

_PATTERN_WEIGHT = 0.8
_KEYWORD_WEIGHT = 0.6
_CONTEXT_MULTIPLIER = 0.7
_NUMBER_FORMAT_WEIGHT = 0.9
_DATA_VALIDATION_WEIGHT = 0.85
_SAMPLE_VALUE_WEIGHT = 0.5
_TIE_CONFIDENCE_CEILING = 0.5  # at/below this, prefer TEXT over guessing between near-tied types

_DATE_FORMAT_HINT = re.compile(r"yy", re.IGNORECASE)
_DATE_FORMAT_COMPANION = re.compile(r"(mmm|mm|dd)", re.IGNORECASE)
_CURRENCY_FORMAT_HINT = re.compile(r"₹|\$|\brs\.?\b|\binr\b", re.IGNORECASE)


def _infer_type_from_number_format(number_format: str) -> Optional[FieldType]:
    if not number_format or number_format in ("General", "@"):
        return None
    if "%" in number_format:
        return FieldType.PERCENTAGE
    if _CURRENCY_FORMAT_HINT.search(number_format):
        return FieldType.AMOUNT
    if _DATE_FORMAT_HINT.search(number_format) and _DATE_FORMAT_COMPANION.search(number_format):
        return FieldType.DATE
    if re.search(r"[0#]", number_format):
        return FieldType.NUMBER
    return None


def _infer_type_from_data_validation(data_validation: Optional[str]) -> Optional[FieldType]:
    # CellRecord only carries the DV rule's formula1 text (see excel_reader.py),
    # not its `type` (list/date/whole/...), so only content we can read out of
    # the formula itself is usable -- a "Yes,No"-style list is the reliable case.
    if not data_validation:
        return None
    lowered = data_validation.lower()
    if "yes" in lowered and "no" in lowered:
        return FieldType.YES_NO
    return None


def _score_text_against_registry(text: str, weight_multiplier: float, scores: dict) -> None:
    if not text:
        return
    lowered = text.lower()
    for field_type, profile in TYPE_REGISTRY.items():
        for pattern in profile.label_patterns:
            if re.search(pattern, lowered, re.IGNORECASE):
                scores[field_type] += _PATTERN_WEIGHT * weight_multiplier
                break
        for keyword in profile.label_keywords:
            if keyword.lower() in lowered:
                scores[field_type] += _KEYWORD_WEIGHT * weight_multiplier
                break


def _score_sample_value(cell: Optional[CellRecord], label: str, cfg: Config, scores: dict) -> None:
    if cell is None or not cell.text:
        return
    sample = cell.text.strip()
    if not sample or len(sample) > 100 or sample.lower() == (label or "").strip().lower():
        return
    for field_type in FieldType:
        verdict = get_type_profile(field_type).validator(sample, cfg)
        if verdict.is_valid:
            scores[field_type] += _SAMPLE_VALUE_WEIGHT


def detect_field_type(
    label: str,
    context: str = "",
    cell: Optional[CellRecord] = None,
    cfg: Optional[Config] = None,
) -> tuple[FieldType, float]:
    scores: dict[FieldType, float] = defaultdict(float)

    if cell is not None:
        nf_type = _infer_type_from_number_format(cell.number_format)
        if nf_type is not None:
            scores[nf_type] += _NUMBER_FORMAT_WEIGHT

        dv_type = _infer_type_from_data_validation(cell.data_validation)
        if dv_type is not None:
            scores[dv_type] += _DATA_VALIDATION_WEIGHT

    _score_text_against_registry(label or "", 1.0, scores)
    _score_text_against_registry(context or "", _CONTEXT_MULTIPLIER, scores)

    if cell is not None and cfg is not None:
        _score_sample_value(cell, label, cfg, scores)

    if not scores or max(scores.values()) <= 0:
        return FieldType.UNKNOWN, 0.0

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_type, top_score = ranked[0]
    runner_up_score = ranked[1][1] if len(ranked) > 1 else 0.0

    total = top_score + runner_up_score
    confidence = max(0.0, min(1.0, top_score / total)) if total > 0 else 0.0

    if confidence <= _TIE_CONFIDENCE_CEILING and runner_up_score > 0:
        return FieldType.TEXT, confidence

    return top_type, confidence
