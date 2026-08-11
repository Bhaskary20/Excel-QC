"""FieldSpec list + response CellRecord list -> matched pairs.

Takes specs from wherever they came from (template_analyzer once it exists,
or hand-built specs in tests today) and pairs each with its cell in a
*response* workbook. Since specs only carry field_name as a string label
(not a stored label-cell position), the label-based strategies below search
the response sheet directly for matching label text rather than re-running
template_analyzer's classification logic.

Strategy ladder, first success wins (see BUILD_PLAN.md Phase 8):
  1-3. Coordinate match, with the sheet resolved by exact name, then
       normalized name (trim/casefold/whitespace), then position (only
       when template and response have the same sheet count).
  4/5. For whatever's still unmatched per sheet: search for a per-field
       offset via label text ("row_offset"), and if >=2 fields on that
       sheet agree on the same nonzero offset, bulk-apply it; anything
       left over falls back to a plain per-field label search
       ("label_match", no offset needed).
  6.   Unmatched -> cell=None. qc_engine records this as MISSING, not
       REVIEW -- the absence is itself the finding.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Optional

from app.config import Config
from app.excel_reader import CellRecord, build_index
from app.models import FieldSpec

_CELL_ADDR_PATTERN = re.compile(r"^([A-Za-z]+)(\d+)$")
_EXTRA_CELLS_CAP = 50


@dataclass(frozen=True)
class FieldMatch:
    spec: FieldSpec
    cell: Optional[CellRecord]
    strategy: str  # exact_coordinate | sheet_name_normalized | sheet_index | row_offset | label_match | unmatched


def _normalize_sheet_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).casefold()


def _normalize_label(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).casefold()


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _split_addr(addr: str) -> tuple[str, int]:
    match = _CELL_ADDR_PATTERN.match(addr)
    if not match:
        raise ValueError(f"not a cell address: {addr!r}")
    return match.group(1), int(match.group(2))


def _shift_row(addr: str, delta: int) -> str:
    col_letters, row = _split_addr(addr)
    return f"{col_letters}{row + delta}"


def _build_sheet_resolution(template_sheets: list[str], response_sheets: list[str]) -> dict[str, tuple[str, str]]:
    """template sheet name -> (resolved response sheet name, strategy used)."""
    response_set = set(response_sheets)
    normalized_response = {_normalize_sheet_name(s): s for s in response_sheets}
    positional = (
        dict(zip(template_sheets, response_sheets))
        if len(template_sheets) == len(response_sheets)
        else {}
    )

    resolution: dict[str, tuple[str, str]] = {}
    for t in template_sheets:
        if t in response_set:
            resolution[t] = (t, "exact_coordinate")
        elif _normalize_sheet_name(t) in normalized_response:
            resolution[t] = (normalized_response[_normalize_sheet_name(t)], "sheet_name_normalized")
        elif t in positional:
            resolution[t] = (positional[t], "sheet_index")

    return resolution


def _try_coordinate_match(
    spec: FieldSpec, index: dict[tuple[str, str], CellRecord], sheet_resolution: dict[str, tuple[str, str]]
) -> Optional[FieldMatch]:
    resolved = sheet_resolution.get(spec.sheet)
    if resolved is None:
        return None
    response_sheet, strategy = resolved
    cell = index.get((response_sheet, spec.cell))
    return FieldMatch(spec=spec, cell=cell, strategy=strategy) if cell is not None else None


def _match_by_label(spec: FieldSpec, response_cells: list[CellRecord], response_sheet: str) -> Optional[CellRecord]:
    """Search the response sheet for a cell whose text equals the spec's
    field_name, then take the cell directly below it (column-header
    convention) or, failing that, directly right of it (row-label
    convention). Without template_analyzer's cell classification available
    here, this can't tell an input apart from another label -- it's a
    best-effort approximation, not a guarantee."""
    target = _normalize_label(spec.field_name)
    if not target:
        return None

    same_sheet = [c for c in response_cells if c.sheet == response_sheet]
    label_matches = [c for c in same_sheet if c.text and _normalize_label(c.text) == target]

    for label_cell in label_matches:
        below = next((c for c in same_sheet if c.col == label_cell.col and c.row == label_cell.row + 1), None)
        if below is not None:
            return below
        right = next((c for c in same_sheet if c.row == label_cell.row and c.col == label_cell.col + 1), None)
        if right is not None:
            return right

    return None


def _detect_row_offset_via_labels(
    specs: list[FieldSpec], response_cells: list[CellRecord], response_sheet: str
) -> Optional[int]:
    offsets: list[int] = []
    for spec in specs:
        guessed = _match_by_label(spec, response_cells, response_sheet)
        if guessed is None:
            continue
        _, template_row = _split_addr(spec.cell)
        offsets.append(guessed.row - template_row)

    if not offsets:
        return None

    modal_offset, frequency = Counter(offsets).most_common(1)[0]
    return modal_offset if modal_offset != 0 and frequency >= 2 else None


def _find_extra_response_cells(
    response_cells: list[CellRecord], matches: list[FieldMatch], cap: int = _EXTRA_CELLS_CAP
) -> list[str]:
    claimed = {(m.cell.sheet, m.cell.cell) for m in matches if m.cell is not None}
    extras = [f"{c.sheet}!{c.cell}" for c in response_cells if c.text and (c.sheet, c.cell) not in claimed]
    return extras[:cap]


def match_fields(
    specs: list[FieldSpec], response_cells: list[CellRecord], cfg: Config
) -> tuple[list[FieldMatch], list[str]]:
    index = build_index(response_cells)
    template_sheets = _ordered_unique([s.sheet for s in specs])
    response_sheets = _ordered_unique([c.sheet for c in response_cells])
    sheet_resolution = _build_sheet_resolution(template_sheets, response_sheets)

    matches: list[FieldMatch] = []
    unmatched: list[FieldSpec] = []

    for spec in specs:
        match = _try_coordinate_match(spec, index, sheet_resolution)
        (matches if match else unmatched).append(match if match else spec)

    by_sheet: dict[str, list[FieldSpec]] = defaultdict(list)
    for spec in unmatched:
        by_sheet[spec.sheet].append(spec)

    still_unmatched: list[FieldSpec] = []
    for sheet_name, sheet_specs in by_sheet.items():
        response_sheet = sheet_resolution.get(sheet_name, (sheet_name, ""))[0]
        offset = _detect_row_offset_via_labels(sheet_specs, response_cells, response_sheet)

        for spec in sheet_specs:
            cell = index.get((response_sheet, _shift_row(spec.cell, offset))) if offset is not None else None
            if cell is not None:
                matches.append(FieldMatch(spec=spec, cell=cell, strategy="row_offset"))
            else:
                still_unmatched.append(spec)

    for spec in still_unmatched:
        response_sheet = sheet_resolution.get(spec.sheet, (spec.sheet, ""))[0]
        cell = _match_by_label(spec, response_cells, response_sheet)
        strategy = "label_match" if cell is not None else "unmatched"
        matches.append(FieldMatch(spec=spec, cell=cell, strategy=strategy))

    extra_cells = _find_extra_response_cells(response_cells, matches)
    return matches, extra_cells
