"""Matched response cell + FieldSpec -> validated ParsedValue list.

Thin orchestration layer: split (Phase 3) -> validate (Phase 4) -> dedupe.
No parsing or validation logic of its own lives here.

Duplicate detection is a deliberate QC signal, not cleanup: a client who
pastes the same phone number 10 times has not provided 10 phone numbers.
The *first* occurrence of a normalized value stays valid; every later
occurrence with the same normalized form is downgraded to invalid with a
reason pointing back at the original (gated by
cfg.parsing.duplicates_are_invalid, default True).
"""

from __future__ import annotations

from typing import Optional

from app.config import Config
from app.excel_reader import CellRecord
from app.models import FieldSpec, ParsedValue, ValueVerdict, get_type_profile
from app.value_splitter import NA_SENTINEL, split_values


def _apply_duplicate_detection(values: list[ParsedValue], cfg: Config) -> list[ParsedValue]:
    if not cfg.parsing.duplicates_are_invalid:
        return values

    seen: dict[str, int] = {}
    result: list[ParsedValue] = []
    for pv in values:
        if pv.verdict.is_valid and pv.verdict.normalized is not None:
            if pv.verdict.normalized in seen:
                first_index = seen[pv.verdict.normalized]
                pv = ParsedValue(
                    index=pv.index,
                    raw=pv.raw,
                    verdict=ValueVerdict(
                        is_valid=False, normalized=None, reason=f"duplicate of value #{first_index}"
                    ),
                )
            else:
                seen[pv.verdict.normalized] = pv.index
        result.append(pv)
    return result


def parse_response(spec: FieldSpec, cell: Optional[CellRecord], cfg: Config) -> tuple[list[ParsedValue], str]:
    if cell is None or not cell.text:
        return [], ""

    tokens = split_values(cell.text, spec.field_type, cfg)

    if tokens == [NA_SENTINEL]:
        na_value = ParsedValue(
            index=1,
            raw=NA_SENTINEL,
            verdict=ValueVerdict(is_valid=True, normalized="N/A", reason="marked not applicable"),
        )
        return [na_value], ""

    note = f"truncated at {cfg.parsing.max_values_per_cell} values" if len(tokens) >= cfg.parsing.max_values_per_cell else ""

    validator = get_type_profile(spec.field_type).validator
    values = [ParsedValue(index=i, raw=token, verdict=validator(token, cfg)) for i, token in enumerate(tokens, start=1)]
    values = _apply_duplicate_detection(values, cfg)

    return values, note
