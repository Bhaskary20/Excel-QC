"""Response cell -> validated slot values, per BUILD_PLAN.md v2 Section 7
Phase F. Pure per-cell parsing: split (Phase C) -> validate (Phase D). Does
not know about N (expected count) or any other cell -- that's
consistency_checker.py, which needs the whole row parsed first before N
(from column H) is even knowable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.config import Config
from app.excel_reader import CellRecord
from app.models import SlotValue, get_validator
from app.slot_parser import parse_slots
from app.template_spec import ColumnSpec, get_column, input_columns


@dataclass(frozen=True)
class ParsedCell:
    column: str
    is_na: bool
    is_unfilled_scaffold: bool
    slot_values: list[SlotValue] = field(default_factory=list)
    note: str = ""


def parse_cell(cell: Optional[CellRecord], column_letter: str, cfg: Config) -> ParsedCell:
    spec: ColumnSpec = get_column(column_letter)
    text = cell.text if cell is not None else None
    result = parse_slots(text, column_letter, cfg)

    slot_values: list[SlotValue] = []
    if not result.is_na and not result.is_unfilled_scaffold:
        validator = get_validator(spec.value_type)
        for slot_num in sorted(result.slots.keys()):
            raw = result.slots[slot_num]
            verdict = validator(raw, cfg, spec)
            slot_values.append(SlotValue(slot=slot_num, raw=raw, verdict=verdict))

    return ParsedCell(
        column=column_letter,
        is_na=result.is_na,
        is_unfilled_scaffold=result.is_unfilled_scaffold,
        slot_values=slot_values,
        note=result.note,
    )


def build_row_index(response_cells: list[CellRecord], sheet: str) -> dict[tuple[int, int], CellRecord]:
    """(row, col) -> CellRecord for one resolved sheet. Built once by the
    caller (qc_engine, Phase G) and reused across all 115 row parses,
    rather than rebuilt per row."""
    return {(c.row, c.col): c for c in response_cells if c.sheet == sheet}


def parse_row_cells(
    row_index: dict[tuple[int, int], CellRecord], response_row: Optional[int], cfg: Config
) -> dict[str, ParsedCell]:
    """Parse all 14 INPUT columns (F, G, H..R, S) for one response row."""
    results: dict[str, ParsedCell] = {}
    for spec in input_columns():
        cell = row_index.get((response_row, spec.index)) if response_row is not None else None
        results[spec.letter] = parse_cell(cell, spec.letter, cfg)
    return results
