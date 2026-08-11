"""Match template plaza rows to response rows, per BUILD_PLAN.md v2 Section
7 Phase E.

Template rows are the 115 known plazas read from template/Format.xlsx
itself (via excel_reader, not hardcoded) -- their S.No / Plaza Code /
Plaza Name / RO / PIU are the reference identity every response row gets
checked against.

Strategy per template row, first success wins:
  1. S.No match -- column A is pre-filled and the client has no reason to
     touch it, so this alone survives inserted/deleted/reordered rows.
  2. Plaza Name match -- unique across all 115 rows (verified in
     BUILD_PLAN.md v2 Section 1.3), the fallback if S.No was altered.
  3. Position -- for whatever's still unmatched, apply the modal row
     offset computed from rows that DID resolve via 1/2. Lowest
     confidence: identity isn't verified this way, only inferred.
  4. Unmatched.

Every matched row is then checked against all 5 identity columns (A-E);
any that differ from the template become identity_mismatches -- editing
"JAITPUR" to something else is a finding, not silently graded through.
Plaza Code (B) is known unreliable in the template itself (2 rows blank,
2 are literally "-"), so a blank/dash template value is never flagged
even if the response fills it in.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from openpyxl.utils import get_column_letter

from app.excel_reader import CellRecord
from app.template_spec import FIRST_DATA_ROW, LAST_DATA_ROW, SHEET_NAME, key_columns

_IDENTITY_COLUMNS: list[str] = [c.letter for c in key_columns()]  # ["A", "B", "C", "D", "E"]
_IDENTITY_LABELS: dict[str, str] = {c.letter: c.header for c in key_columns()}
_PLAZA_CODE_UNRELIABLE_TOKENS = {"", "-"}


@dataclass(frozen=True)
class RowMatch:
    template_s_no: int
    template_plaza_code: str
    template_plaza_name: str
    template_ro: str
    template_piu: str
    response_row: Optional[int]
    match_strategy: str  # "s_no" | "plaza_name" | "position" | "unmatched"
    identity_mismatches: list[str] = field(default_factory=list)


def _normalize_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).casefold()


def resolve_sheet(cells: list[CellRecord], preferred: str) -> Optional[str]:
    sheets = {c.sheet for c in cells}
    if preferred in sheets:
        return preferred
    if len(sheets) == 1:
        return next(iter(sheets))
    return None


def _build_identity_index(cells: list[CellRecord], sheet: Optional[str]) -> dict[int, dict[str, str]]:
    """row number -> {column letter: text} for the 5 identity columns (A-E)."""
    index: dict[int, dict[str, str]] = defaultdict(dict)
    if sheet is None:
        return index
    identity_cols = set(_IDENTITY_COLUMNS)
    for c in cells:
        if c.sheet != sheet:
            continue
        col_letter = get_column_letter(c.col)
        if col_letter in identity_cols:
            index[c.row][col_letter] = c.text
    return index


def _parse_s_no(text: str) -> Optional[int]:
    text = text.strip()
    return int(text) if text.isdigit() else None


def _build_row_match(
    template_identity: dict[str, str],
    s_no: int,
    response_row: Optional[int],
    strategy: str,
    response_index: dict[int, dict[str, str]],
) -> RowMatch:
    mismatches: list[str] = []
    if response_row is not None:
        response_identity = response_index.get(response_row, {})
        for letter in _IDENTITY_COLUMNS:
            expected = template_identity.get(letter, "").strip()
            actual = response_identity.get(letter, "").strip()
            if letter == "B" and expected in _PLAZA_CODE_UNRELIABLE_TOKENS:
                continue  # template's own Plaza Code is blank/"-" for 4 rows; not a real value to check against
            if expected and actual and _normalize_key(expected) != _normalize_key(actual):
                mismatches.append(f"{_IDENTITY_LABELS[letter]}: expected {expected!r}, got {actual!r}")
    else:
        strategy = "unmatched"

    return RowMatch(
        template_s_no=s_no,
        template_plaza_code=template_identity.get("B", ""),
        template_plaza_name=template_identity.get("C", ""),
        template_ro=template_identity.get("D", ""),
        template_piu=template_identity.get("E", ""),
        response_row=response_row,
        match_strategy=strategy,
        identity_mismatches=mismatches,
    )


def match_rows(template_cells: list[CellRecord], response_cells: list[CellRecord]) -> list[RowMatch]:
    template_sheet = resolve_sheet(template_cells, SHEET_NAME)
    response_sheet = resolve_sheet(response_cells, SHEET_NAME)

    template_index = _build_identity_index(template_cells, template_sheet)
    response_index = _build_identity_index(response_cells, response_sheet)

    response_by_s_no: dict[int, int] = {}
    response_by_plaza_name: dict[str, int] = {}
    for row, identity in response_index.items():
        s_no = _parse_s_no(identity.get("A", ""))
        if s_no is not None and s_no not in response_by_s_no:
            response_by_s_no[s_no] = row
        plaza_name = _normalize_key(identity.get("C", ""))
        if plaza_name and plaza_name not in response_by_plaza_name:
            response_by_plaza_name[plaza_name] = row

    template_rows = sorted(
        row
        for row in template_index
        if FIRST_DATA_ROW <= row <= LAST_DATA_ROW and _parse_s_no(template_index[row].get("A", "")) is not None
    )

    matches: list[RowMatch] = []
    offsets: list[int] = []

    for row in template_rows:
        identity = template_index[row]
        s_no = _parse_s_no(identity.get("A", ""))
        plaza_name_key = _normalize_key(identity.get("C", ""))

        response_row = response_by_s_no.get(s_no)
        strategy = "s_no"

        if response_row is None:
            response_row = response_by_plaza_name.get(plaza_name_key)
            strategy = "plaza_name"

        if response_row is not None:
            offsets.append(response_row - row)

        matches.append(_build_row_match(identity, s_no, response_row, strategy, response_index))

    if offsets:
        modal_offset, frequency = Counter(offsets).most_common(1)[0]
    else:
        modal_offset, frequency = None, 0

    if modal_offset is not None and frequency >= 2:
        # A row already claimed by a real (s_no/plaza_name) match must never
        # be stolen by a position guess for a *different* template row --
        # e.g. a genuinely deleted row must not get remapped onto the row
        # its neighbor shifted into.
        claimed_rows = {m.response_row for m in matches if m.response_row is not None}
        for i, row in enumerate(template_rows):
            if matches[i].response_row is not None:
                continue
            guess_row = row + modal_offset
            if guess_row in claimed_rows:
                continue
            if guess_row in response_index and any(v.strip() for v in response_index[guess_row].values()):
                identity = template_index[row]
                s_no = _parse_s_no(identity.get("A", ""))
                matches[i] = _build_row_match(identity, s_no, guess_row, "position", response_index)
                claimed_rows.add(guess_row)

    return matches
