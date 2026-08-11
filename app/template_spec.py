"""Declarative description of template/Format.xlsx, sheet "Data Sheet for
UP STF" -- the single source of truth every other module reads instead of
inferring structure at runtime.

The header strings and scaffold strings below are copied verbatim (via
repr()) from the real file, including its own irregularities -- e.g. column
J's scaffold has a space before ")" in "(dd/mm/yyyy )" but not in the
second "(dd/mm/yyyy)". Do not "clean up" these strings; they must match the
template byte-for-byte or the header/scaffold tripwire tests
(tests/test_template_spec.py) will fail on purpose.

ColumnSpec.scaffold_raw stores the *complete* pre-filled cell text (all 6
slots), not a hand-extracted single-slot placeholder -- slot_parser.py
(Phase C) strips numbering from this the same way it strips numbering from
a response cell, so the "is this slot still just the placeholder" check
uses one algorithm on both sides instead of a second, hand-transcribed copy
that could drift out of sync.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

SHEET_NAME = "Data Sheet for UP STF"
HEADER_ROW = 2
FIRST_DATA_ROW = 3
LAST_DATA_ROW = 117
TOTAL_DATA_ROWS = LAST_DATA_ROW - FIRST_DATA_ROW + 1  # 115

SCAFFOLD_SLOTS = 6  # soft cap -- the Instructions sheet permits more
ANCHOR_COLUMN = "H"  # column that determines N (agency count) for a row

CONTRACT_WINDOW = (date(2021, 1, 1), date(2026, 1, 14))


class Role(str, Enum):
    KEY = "KEY"  # pre-filled by NHAI: identity/reference, never client-graded
    INPUT = "INPUT"  # the client fills this in


class ValueType(str, Enum):
    INTEGER = "INTEGER"
    TEXT = "TEXT"
    COMPOSITE_LOCATION = "COMPOSITE_LOCATION"
    ENUM = "ENUM"
    NAME = "NAME"
    PHONE = "PHONE"
    DATE_RANGE = "DATE_RANGE"
    ADDRESS = "ADDRESS"
    NUMBER = "NUMBER"


@dataclass(frozen=True)
class ColumnSpec:
    letter: str
    index: int  # 1-based column number, e.g. "A" -> 1
    header: str  # verbatim from the template, row 2
    role: Role
    value_type: ValueType
    slotted: bool  # True for H..R: cell holds up to N numbered sub-values
    required: bool  # False only for S (Remarks); irrelevant for KEY columns
    match_key: bool = False  # usable by row_matcher to identify a row (A, C)
    scaffold_raw: Optional[str] = None  # verbatim pre-filled text, slotted columns only
    composite_components: tuple[str, ...] = ()  # F only
    enum_values: tuple[str, ...] = ()  # G, I only
    # canonical enum value -> alternate phrasings that should still match it,
    # e.g. I's "3 months" alone (no "EQ" prefix) -> "EQ (3 months)". Only I
    # needs this; G's values are already distinct standalone words.
    enum_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)


_SCAFFOLD_BLANK = "  1. \n  2. \n  3.\n  4. \n  5.\n  6."

COLUMNS: dict[str, ColumnSpec] = {
    "A": ColumnSpec(
        letter="A", index=1, header="S.No",
        role=Role.KEY, value_type=ValueType.INTEGER,
        slotted=False, required=True, match_key=True,
    ),
    "B": ColumnSpec(
        letter="B", index=2, header="Plaza Code",
        role=Role.KEY, value_type=ValueType.TEXT,
        slotted=False, required=True,
        # NOT a match_key: 2 rows blank (104, 105), 2 rows are literally "-" (25, 96).
    ),
    "C": ColumnSpec(
        letter="C", index=3, header="Plaza Name",
        role=Role.KEY, value_type=ValueType.TEXT,
        slotted=False, required=True, match_key=True,
    ),
    "D": ColumnSpec(
        letter="D", index=4, header="RO",
        role=Role.KEY, value_type=ValueType.TEXT,
        slotted=False, required=True,
    ),
    "E": ColumnSpec(
        letter="E", index=5, header="PIU",
        role=Role.KEY, value_type=ValueType.TEXT,
        slotted=False, required=True,
    ),
    "F": ColumnSpec(
        letter="F", index=6, header="Plaza - Village, Location",
        role=Role.INPUT, value_type=ValueType.COMPOSITE_LOCATION,
        slotted=False, required=True,
        composite_components=("village_name", "chainage", "city_name", "pincode"),
    ),
    "G": ColumnSpec(
        letter="G", index=7, header="Plaza Type",
        role=Role.INPUT, value_type=ValueType.ENUM,
        slotted=False, required=True,
        enum_values=("Public Funded", "BOT", "TOT", "Invit", "MLFF"),
        # "PF" is the standard NHAI shorthand for Public Funded -- the
        # overwhelming majority of real responses write it this way rather
        # than the spelled-out form. "FP" covers the same abbreviation
        # transposed, seen occasionally in real data too.
        enum_aliases={"Public Funded": ("pf", "fp")},
    ),
    "H": ColumnSpec(
        letter="H", index=8, header="Agency name \n (Pl. list all contracts in said period)",
        role=Role.INPUT, value_type=ValueType.TEXT,
        slotted=True, required=True,
        scaffold_raw="  1. Agency \n  2. Agency \n  3. Agency \n  4. Agency\n  5. Agency \n  6. Agency",
    ),
    "I": ColumnSpec(
        letter="I", index=9, header="EQ (3 months)/ Regular (1 year)",
        role=Role.INPUT, value_type=ValueType.ENUM,
        slotted=True, required=True,
        scaffold_raw=_SCAFFOLD_BLANK,
        enum_values=("EQ (3 months)", "Regular (1 year)"),
        enum_aliases={
            "EQ (3 months)": ("eq", "3 month", "3months"),
            "Regular (1 year)": ("regular", "1 year", "1year", "annual"),
        },
    ),
    "J": ColumnSpec(
        letter="J", index=10, header="Contract Start & End date with extension (01/01/2021 - 14/01/2026)",
        role=Role.INPUT, value_type=ValueType.DATE_RANGE,
        slotted=True, required=True,
        scaffold_raw=(
            "  1. From (dd/mm/yyyy ) - To (dd/mm/yyyy) \n"
            "  2. From (dd/mm/yyyy ) - To (dd/mm/yyyy) \n"
            "  3. From (dd/mm/yyyy ) - To (dd/mm/yyyy) \n"
            "  4. From (dd/mm/yyyy ) - To (dd/mm/yyyy) \n"
            "  5. From (dd/mm/yyyy ) - To (dd/mm/yyyy) \n"
            "  6. From (dd/mm/yyyy ) - To (dd/mm/yyyy)"
        ),
    ),
    "K": ColumnSpec(
        letter="K", index=11, header="Name of Toll Plaza Manager",
        role=Role.INPUT, value_type=ValueType.NAME,
        slotted=True, required=True, scaffold_raw=_SCAFFOLD_BLANK,
    ),
    "L": ColumnSpec(
        letter="L", index=12, header="Contact of Toll Manager",
        role=Role.INPUT, value_type=ValueType.PHONE,
        slotted=True, required=True, scaffold_raw=_SCAFFOLD_BLANK,
    ),
    "M": ColumnSpec(
        letter="M", index=13, header="Address of Toll Agency",
        role=Role.INPUT, value_type=ValueType.ADDRESS,
        slotted=True, required=True, scaffold_raw=_SCAFFOLD_BLANK,
    ),
    "N": ColumnSpec(
        letter="N", index=14, header="Supervision Consultant (AE / IE) name and its address",
        role=Role.INPUT, value_type=ValueType.TEXT,
        slotted=True, required=True, scaffold_raw=_SCAFFOLD_BLANK,
    ),
    "O": ColumnSpec(
        letter="O", index=15, header="Team Leader name (AE/ IE ) during the said Contract Period",
        role=Role.INPUT, value_type=ValueType.NAME,
        slotted=True, required=True, scaffold_raw=_SCAFFOLD_BLANK,
    ),
    "P": ColumnSpec(
        letter="P", index=16, header="HTMS / Toll Expert during said contract period",
        role=Role.INPUT, value_type=ValueType.TEXT,
        slotted=True, required=True, scaffold_raw=_SCAFFOLD_BLANK,
    ),
    "Q": ColumnSpec(
        letter="Q", index=17, header="Per Day Average Traffic Count during the said contract period of Agency",
        role=Role.INPUT, value_type=ValueType.NUMBER,
        slotted=True, required=True, scaffold_raw=_SCAFFOLD_BLANK,
    ),
    "R": ColumnSpec(
        letter="R", index=18, header="Average Traffic Count of Exempted vehicles during the said contract period of Agency",
        role=Role.INPUT, value_type=ValueType.NUMBER,
        slotted=True, required=True, scaffold_raw=_SCAFFOLD_BLANK,
    ),
    "S": ColumnSpec(
        letter="S", index=19, header="Remarks",
        role=Role.INPUT, value_type=ValueType.TEXT,
        slotted=False, required=False,
    ),
}

COLUMN_LETTERS: tuple[str, ...] = tuple(COLUMNS.keys())


def get_column(letter: str) -> ColumnSpec:
    return COLUMNS[letter]


def key_columns() -> list[ColumnSpec]:
    return [c for c in COLUMNS.values() if c.role == Role.KEY]


def match_key_columns() -> list[ColumnSpec]:
    return [c for c in COLUMNS.values() if c.match_key]


def input_columns() -> list[ColumnSpec]:
    return [c for c in COLUMNS.values() if c.role == Role.INPUT]


def slotted_columns() -> list[ColumnSpec]:
    return [c for c in COLUMNS.values() if c.slotted]
