"""Label/context/sheet-structure -> ExpectedCount.

Six strategies are tried in priority order (see BUILD_PLAN.md Phase 6); the
first one whose result clears cfg.expected_count.min_confidence_to_accept
wins. If none does, the result is count=None, source=UNKNOWN -- the system
never invents a number.

Priority order and default confidence:
  1. Explicit quantity in instruction text      0.95 (0.85 for "at least",
                                                       0.70 for "up to")
  2. Numbered range ("1-10", "S.No. 1-10")      0.90
  3. Enumerated labels ("Person 1" .. "Person 10" as sibling cells)  0.90
  4. Table rows (a sequential 1..N row-number column near the field) 0.80
  5. Data validation constraint on the cell     0.65
  6. Singular-label heuristic (opt-in via cfg.expected_count.assume_single_when_unknown) 0.55

Strategy 4 is a narrower approximation than the plan's original description:
CellRecord (Phase 1) doesn't carry border/fill styling, so this looks for a
sequential S.No.-style column near the field instead of detecting a
bordered table block directly.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from app.config import Config
from app.excel_reader import CellRecord
from app.models import CountSource, ExpectedCount

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "dozen": 12,
}
_NUMBER_WORD_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(_NUMBER_WORDS.keys(), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

_MIN_PATTERN = re.compile(r"\b(?:minimum|min\.?|at\s+least)\s+(\d{1,3})\b", re.IGNORECASE)
_MAX_PATTERN = re.compile(r"\b(?:maximum|max\.?|up\s+to|not\s+more\s+than)\s+(\d{1,3})\b", re.IGNORECASE)
_EXACT_PATTERNS = [
    re.compile(r"\b(?:provide|give|enter|list|furnish|attach|mention|fill)\s+(?:any\s+|all\s+)?(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,3})\s*(?:nos?\.?|numbers?|values?|entries|items|persons?|records?)\b", re.IGNORECASE),
    re.compile(r"\(\s*(\d{1,3})\s*(?:nos?\.?)?\s*\)"),
    re.compile(r"\btop\s+(\d{1,3})\b", re.IGNORECASE),
]

_SNO_RANGE_PATTERN = re.compile(r"\bS\.?\s*No\.?\s*(\d{1,3})\s*(?:-|–|to)\s*(\d{1,3})\b", re.IGNORECASE)
_GENERIC_RANGE_PATTERN = re.compile(r"\b(\d{1,3})\s*(?:-|–|to)\s*(\d{1,3})\b", re.IGNORECASE)

_TRAILING_NUMBER_PATTERN = re.compile(r"^(.*?)\s*(\d{1,3})$")
_PURE_INTEGER_PATTERN = re.compile(r"^\d{1,3}$")
_DV_MAX_PATTERN = re.compile(r"<=?\s*(\d{1,3})")

_QUANTITY_WORD_PATTERN = re.compile(
    r"\b(provide|list|enter|give|numbers?|values?|entries|items|persons?|records?|\d+)\b", re.IGNORECASE
)
_PLURAL_HINT_PATTERN = re.compile(r"s$", re.IGNORECASE)


def _normalize_number_words(text: str) -> str:
    return _NUMBER_WORD_PATTERN.sub(lambda m: str(_NUMBER_WORDS[m.group(0).lower()]), text)


def _is_sane_count(count: int, cfg: Config) -> bool:
    return 1 <= count <= cfg.expected_count.max_sane_count


def _detect_explicit_instruction(text: str, cfg: Config) -> Optional[ExpectedCount]:
    normalized = _normalize_number_words(text)

    match = _MIN_PATTERN.search(normalized)
    if match and _is_sane_count(int(match.group(1)), cfg):
        return ExpectedCount(
            count=int(match.group(1)), source=CountSource.EXPLICIT_INSTRUCTION,
            confidence=0.85, evidence=f"minimum-quantity phrase ('{match.group(0)}')", bound="min",
        )

    match = _MAX_PATTERN.search(normalized)
    if match and _is_sane_count(int(match.group(1)), cfg):
        return ExpectedCount(
            count=int(match.group(1)), source=CountSource.EXPLICIT_INSTRUCTION,
            confidence=0.70, evidence=f"maximum-quantity phrase ('{match.group(0)}')", bound="max",
        )

    for pattern in _EXACT_PATTERNS:
        match = pattern.search(normalized)
        if match and _is_sane_count(int(match.group(1)), cfg):
            return ExpectedCount(
                count=int(match.group(1)), source=CountSource.EXPLICIT_INSTRUCTION,
                confidence=0.95, evidence=f"explicit quantity phrase ('{match.group(0)}')", bound="exact",
            )

    return None


def _detect_numbered_range(text: str, cfg: Config) -> Optional[ExpectedCount]:
    for pattern, evidence_prefix in ((_SNO_RANGE_PATTERN, "S.No. range"), (_GENERIC_RANGE_PATTERN, "numeric range")):
        match = pattern.search(text)
        if not match:
            continue
        lo, hi = int(match.group(1)), int(match.group(2))
        if 1 <= lo < hi <= cfg.expected_count.max_sane_count:
            return ExpectedCount(
                count=hi - lo + 1, source=CountSource.NUMBERED_RANGE, confidence=0.90,
                evidence=f"{evidence_prefix} ('{match.group(0)}')", bound="exact",
            )
    return None


def _longest_enumerated_run(cells: list[CellRecord]) -> Optional[list[int]]:
    """Longest run of consecutive same-prefix, trailing-number cells among
    the given (already column- or row-sorted) non-blank cells -- e.g.
    "Person 1", "Person 2", ... "Person 10". Gaps from intervening blank
    cells are tolerated since those were already filtered out by the caller."""
    best: list[int] = []
    current: list[int] = []
    current_prefix: Optional[str] = None

    for c in cells:
        match = _TRAILING_NUMBER_PATTERN.match(c.text.strip())
        prefix = match.group(1).strip().lower() if match else None
        if match and prefix and prefix == current_prefix:
            current.append(int(match.group(2)))
        elif match and prefix:
            current = [int(match.group(2))]
            current_prefix = prefix
        else:
            current = []
            current_prefix = None

        if len(current) > len(best):
            best = current

    return best if best else None


def _detect_enumerated_labels(cell: CellRecord, sheet_cells: list[CellRecord], cfg: Config) -> Optional[ExpectedCount]:
    same_col = sorted((c for c in sheet_cells if c.col == cell.col and c.text), key=lambda c: c.row)
    same_row = sorted((c for c in sheet_cells if c.row == cell.row and c.text), key=lambda c: c.col)

    for group in (same_col, same_row):
        run = _longest_enumerated_run(group)
        if run and len(run) >= 3:
            highest = max(run)
            return ExpectedCount(
                count=highest, source=CountSource.ENUMERATED_LABELS, confidence=0.90,
                evidence=f"enumerated labels up to {highest} found in template", bound="exact",
            )
    return None


def _detect_table_rows(cell: CellRecord, sheet_cells: list[CellRecord], cfg: Config) -> Optional[ExpectedCount]:
    candidates = [
        c for c in sheet_cells
        if c.row > cell.row
        and abs(c.col - cell.col) <= cfg.expected_count.scan_radius
        and _PURE_INTEGER_PATTERN.match(c.text.strip())
    ]
    if not candidates:
        return None

    by_col: dict[int, list[CellRecord]] = defaultdict(list)
    for c in candidates:
        by_col[c.col].append(c)

    for cells_in_col in by_col.values():
        cells_in_col.sort(key=lambda c: c.row)
        values = [int(c.text.strip()) for c in cells_in_col]
        if len(values) >= 3 and values[0] == 1 and values == list(range(1, len(values) + 1)):
            return ExpectedCount(
                count=len(values), source=CountSource.TABLE_ROWS, confidence=0.80,
                evidence=f"sequential 1..{len(values)} row-number column found near field", bound="exact",
            )
    return None


def _detect_data_validation_count(
    cell: CellRecord, context_cells: list[CellRecord], cfg: Config
) -> Optional[ExpectedCount]:
    for c in [cell, *context_cells]:
        if not c or not c.data_validation:
            continue
        match = _DV_MAX_PATTERN.search(c.data_validation)
        if match and _is_sane_count(int(match.group(1)), cfg):
            return ExpectedCount(
                count=int(match.group(1)), source=CountSource.DATA_VALIDATION, confidence=0.65,
                evidence=f"data validation constraint ('{c.data_validation}')", bound="max",
            )
    return None


def _detect_singular_label(label: str, cfg: Config) -> Optional[ExpectedCount]:
    if not cfg.expected_count.assume_single_when_unknown:
        return None

    text = (label or "").strip()
    if not text or len(text) > 60:
        return None
    if _QUANTITY_WORD_PATTERN.search(text):
        return None
    if _PLURAL_HINT_PATTERN.search(text.rstrip(".:")):
        return None

    return ExpectedCount(
        count=1, source=CountSource.SINGULAR_LABEL, confidence=0.55,
        evidence=f"label '{label}' reads as singular with no quantity signal", bound="exact",
    )


def detect_expected_count(
    field_label: str,
    context_cells: list[CellRecord],
    sheet_cells: list[CellRecord],
    cell: Optional[CellRecord],
    cfg: Config,
) -> ExpectedCount:
    combined_text = " ".join([field_label or ""] + [c.text for c in context_cells if c and c.text])
    threshold = cfg.expected_count.min_confidence_to_accept

    candidates = [
        _detect_explicit_instruction(combined_text, cfg),
        _detect_numbered_range(combined_text, cfg),
        _detect_enumerated_labels(cell, sheet_cells, cfg) if cell else None,
        _detect_table_rows(cell, sheet_cells, cfg) if cell else None,
        _detect_data_validation_count(cell, context_cells, cfg) if cell else None,
        _detect_singular_label(field_label, cfg),
    ]

    for candidate in candidates:
        if candidate is not None and candidate.confidence >= threshold:
            return candidate

    return ExpectedCount(
        count=None, source=CountSource.UNKNOWN, confidence=0.20,
        evidence="no quantity signal found", bound="exact",
    )
