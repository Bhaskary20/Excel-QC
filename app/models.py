"""Domain model for the Excel QC engine.

Every dataclass and enum shared across modules lives here so signatures
don't churn as later phases are built. Nothing in this file touches
openpyxl, regex parsing, or validation logic — it only defines shapes.

TYPE_REGISTRY is the single place that knows about the set of supported
field types (FieldType.PHONE, .AMOUNT, ...). Adding a new type means adding
one entry here and, if it needs custom validation, one function in
validators.py — no other module should ever branch on FieldType directly.

The `validator` on each TypeProfile is a placeholder until Phase 4
(validators.py) registers the real per-type validator by assigning
TYPE_REGISTRY[<type>].validator = <function>. Until then it treats any
non-empty value as provisionally valid, which keeps earlier phases
(splitter, template analysis) testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from app.config import Config


# ============================================================================
# Field type
# ============================================================================


class FieldType(str, Enum):
    PHONE = "PHONE"
    NAME = "NAME"
    EMAIL = "EMAIL"
    AMOUNT = "AMOUNT"
    DATE = "DATE"
    ADDRESS = "ADDRESS"
    LOCATION = "LOCATION"
    NUMBER = "NUMBER"
    PERCENTAGE = "PERCENTAGE"
    CHAINAGE = "CHAINAGE"
    COORDINATE = "COORDINATE"
    YES_NO = "YES_NO"
    TEXT = "TEXT"
    DOCUMENT_REFERENCE = "DOCUMENT_REFERENCE"
    UNKNOWN = "UNKNOWN"


@dataclass
class ValueVerdict:
    """Result of validating a single parsed value."""

    is_valid: bool
    normalized: Optional[str]  # canonical form, e.g. "250000" for "₹2,50,000"
    reason: str = ""  # shape description only, e.g. "expected 10 digits, got 4"
    # NEVER put the raw client value in `reason` -- it lands directly in QC_Report.xlsx.


def _validator_not_implemented(value: str, cfg: "Config") -> ValueVerdict:
    text = value.strip()
    if text:
        return ValueVerdict(is_valid=True, normalized=text, reason="")
    return ValueVerdict(is_valid=False, normalized=None, reason="empty value")


@dataclass
class TypeProfile:
    """Static, registry-owned metadata for one FieldType."""

    type: FieldType
    label_keywords: list[str] = field(default_factory=list)
    label_patterns: list[str] = field(default_factory=list)  # regex, higher precision than keywords
    allowed_separators: list[str] = field(default_factory=list)  # subset of ["\n", ";", "|", ",", "/"]
    forbidden_separators: list[str] = field(default_factory=list)
    validator: Callable[[str, "Config"], ValueVerdict] = _validator_not_implemented
    plural_hint: bool = False  # does a plural label suggest a multi-value field?


TYPE_REGISTRY: dict[FieldType, TypeProfile] = {
    FieldType.PHONE: TypeProfile(
        type=FieldType.PHONE,
        label_keywords=["phone", "mobile", "contact", "cell", "whatsapp", "tel"],
        label_patterns=[r"\b(phone|mobile|contact\s*(no|number)?|cell|whatsapp|tel)\b"],
        allowed_separators=["\n", ";", ",", "|", "/"],
        forbidden_separators=[],
        plural_hint=True,
    ),
    FieldType.NAME: TypeProfile(
        type=FieldType.NAME,
        label_keywords=["name", "person", "owner", "beneficiary", "contractor", "applicant"],
        label_patterns=[r"\b(name|person|owner|beneficiary|contractor|applicant)s?\b"],
        allowed_separators=["\n", ";", "|", ","],
        forbidden_separators=["/"],
        plural_hint=True,
    ),
    FieldType.EMAIL: TypeProfile(
        type=FieldType.EMAIL,
        label_keywords=["email", "mail", "e-mail"],
        label_patterns=[r"\b(e-?mail|mail\s*id)\b"],
        allowed_separators=["\n", ";", ",", "|"],
        forbidden_separators=["/"],
        plural_hint=False,
    ),
    FieldType.AMOUNT: TypeProfile(
        type=FieldType.AMOUNT,
        label_keywords=["amount", "compensation", "cost", "value", "price", "payment", "rs", "inr"],
        label_patterns=[r"\b(amount|compensation|cost|value|price|payment)\b|₹|\brs\.?\b|\binr\b"],
        # "," is allowed but only ever used via value_splitter's digit-guard,
        # so "₹2,50,000" (a single grouped amount) never gets exploded.
        allowed_separators=["\n", ";", "|", ","],
        forbidden_separators=["/", "."],
        plural_hint=True,
    ),
    FieldType.DATE: TypeProfile(
        type=FieldType.DATE,
        label_keywords=["date", "dated", "dt", "deadline"],
        label_patterns=[r"\b(date|dated|dt\.?|as\s+on|deadline|d\.o\.b)\b"],
        allowed_separators=["\n", ";", ",", "|"],
        forbidden_separators=["/", "-", "."],
        plural_hint=False,
    ),
    FieldType.ADDRESS: TypeProfile(
        type=FieldType.ADDRESS,
        label_keywords=["address", "residence", "door no", "h no"],
        label_patterns=[r"\b(address|residence|door\s*no|h\.?\s*no)\b"],
        allowed_separators=["\n", ";", "|"],
        forbidden_separators=[",", "/"],
        plural_hint=True,
    ),
    FieldType.LOCATION: TypeProfile(
        type=FieldType.LOCATION,
        label_keywords=["location", "village", "mandal", "district", "site", "place"],
        label_patterns=[r"\b(location|village|mandal|district|site|place)\b"],
        allowed_separators=["\n", ";", "|"],
        forbidden_separators=[","],
        plural_hint=True,
    ),
    FieldType.NUMBER: TypeProfile(
        type=FieldType.NUMBER,
        label_keywords=["number", "count", "quantity", "qty"],
        label_patterns=[r"\b(count|quantity|qty|no\.)\b"],
        allowed_separators=["\n", ";", "|", ","],
        forbidden_separators=["/", "."],
        plural_hint=True,
    ),
    FieldType.PERCENTAGE: TypeProfile(
        type=FieldType.PERCENTAGE,
        label_keywords=["percent", "percentage"],
        label_patterns=[r"\b(percent(age)?)\b|%"],
        allowed_separators=["\n", ";", ",", "|"],
        forbidden_separators=["/"],
        plural_hint=False,
    ),
    FieldType.CHAINAGE: TypeProfile(
        type=FieldType.CHAINAGE,
        label_keywords=["chainage", "ch", "km"],
        label_patterns=[r"\b(chainage|ch\.?)\b|\bkm\b"],
        allowed_separators=["\n", ";", ",", "|"],
        forbidden_separators=["/", "+"],
        plural_hint=True,
    ),
    FieldType.COORDINATE: TypeProfile(
        type=FieldType.COORDINATE,
        label_keywords=["coordinate", "lat", "long", "latitude", "longitude", "gps"],
        label_patterns=[r"\b(coordinate|lat(itude)?|long(itude)?|gps)\b"],
        allowed_separators=["\n", ";", "|"],
        forbidden_separators=[","],
        plural_hint=True,
    ),
    FieldType.YES_NO: TypeProfile(
        type=FieldType.YES_NO,
        label_keywords=["yes/no", "y/n", "whether"],
        label_patterns=[r"\b(yes\s*/\s*no|y\s*/\s*n|whether)\b"],
        allowed_separators=["\n", ";", ",", "|"],
        forbidden_separators=[],
        plural_hint=False,
    ),
    FieldType.TEXT: TypeProfile(
        type=FieldType.TEXT,
        label_keywords=["remarks", "comments", "notes", "description", "details"],
        label_patterns=[r"\b(remarks?|comments?|notes?|description|details)\b"],
        allowed_separators=["\n", ";"],
        forbidden_separators=[",", "/"],
        plural_hint=False,
    ),
    FieldType.DOCUMENT_REFERENCE: TypeProfile(
        type=FieldType.DOCUMENT_REFERENCE,
        label_keywords=["reference", "ref no", "document no", "file no", "order no"],
        label_patterns=[r"\b(ref(erence)?\s*(no\.?|number)?|document\s*no\.?|file\s*no\.?|order\s*no\.?)\b"],
        allowed_separators=["\n", ";", ",", "|"],
        forbidden_separators=["/"],
        plural_hint=True,
    ),
    FieldType.UNKNOWN: TypeProfile(
        type=FieldType.UNKNOWN,
        label_keywords=[],
        label_patterns=[],
        allowed_separators=["\n", ";"],
        forbidden_separators=[",", "/"],
        plural_hint=False,
    ),
}


def get_type_profile(field_type: FieldType) -> TypeProfile:
    """Registry lookup with a safe fallback to UNKNOWN's (conservative) profile."""
    return TYPE_REGISTRY.get(field_type, TYPE_REGISTRY[FieldType.UNKNOWN])


# ============================================================================
# Status model
# ============================================================================


class Status(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    INVALID = "INVALID"
    REVIEW = "REVIEW"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# ============================================================================
# Expected count
# ============================================================================


class CountSource(str, Enum):
    EXPLICIT_INSTRUCTION = "explicit_instruction"
    NUMBERED_RANGE = "numbered_range"
    ENUMERATED_LABELS = "enumerated_labels"
    TABLE_ROWS = "table_rows"
    DATA_VALIDATION = "data_validation"
    SINGULAR_LABEL = "singular_label"
    SEMANTIC = "semantic"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ExpectedCount:
    count: Optional[int]
    source: CountSource
    confidence: float  # 0.0 - 1.0
    evidence: str = ""  # short template-derived justification, never client data
    bound: str = "exact"  # "exact" | "min" | "max" -- see BUILD_PLAN.md Phase 6


# ============================================================================
# Template schema (produced by template_analyzer.py, Phase 7)
# ============================================================================


@dataclass(frozen=True)
class FieldSpec:
    sheet: str
    cell: str
    field_name: str
    field_type: FieldType
    field_type_confidence: float
    expected: ExpectedCount
    required: bool = True
    source: str = "unknown"  # how field_name was resolved: column_header | row_label | ... | coordinate
    context_text: str = ""  # harvested instruction/context text used for detection


# ============================================================================
# Parsed / validated response values
# ============================================================================


@dataclass(frozen=True)
class ParsedValue:
    index: int  # 1-based position within the cell
    raw: str
    verdict: ValueVerdict


# ============================================================================
# QC result (per field/cell, Phase 10) and rollups (Phase 10/11)
# ============================================================================


@dataclass(frozen=True)
class QCResult:
    sheet: str
    cell: str
    field_name: str
    field_type: FieldType
    expected_count: Optional[int]
    detected_count: int
    valid_count: int
    invalid_count: int
    missing_count: Optional[int]
    completeness: Optional[float]
    status: Status
    confidence: float
    reason: str
    values: list[ParsedValue] = field(default_factory=list)


@dataclass
class SheetSummary:
    sheet: str
    expected_responses: int = 0
    valid_responses: int = 0
    missing: int = 0
    invalid: int = 0
    partial_cells: int = 0
    complete_cells: int = 0
    completeness: Optional[float] = None


@dataclass
class WorkbookSummary:
    total_sheets: int = 0
    total_cells_checked: int = 0
    total_expected: int = 0
    total_valid: int = 0
    total_missing: int = 0
    total_invalid: int = 0
    complete_cells: int = 0
    partial_cells: int = 0
    missing_cells: int = 0
    invalid_cells: int = 0
    review_cells: int = 0
    not_applicable_cells: int = 0
    overall_completeness: Optional[float] = None


@dataclass
class QCRun:
    template_path: str
    response_path: str
    generated_at: datetime = field(default_factory=datetime.now)
    engine_version: str = "0.1.0"
    ai_enabled: bool = False
    results: list[QCResult] = field(default_factory=list)
    sheet_summaries: list[SheetSummary] = field(default_factory=list)
    workbook_summary: WorkbookSummary = field(default_factory=WorkbookSummary)
    extra_response_cells: list[str] = field(default_factory=list)  # response content with no matching FieldSpec
