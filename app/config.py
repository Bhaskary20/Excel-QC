"""Configuration loading for the Excel QC engine.

Everything tunable lives in config/default.yaml. load_config() reads that
file, optionally deep-merges an override YAML file and/or an in-memory
overrides dict (used by the CLI for flags like --no-ai), and returns a
frozen, attribute-accessible Config object.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, ConfigDict

# Running from source, app/config.py's parent.parent is the repo root. Inside
# a PyInstaller onefile bundle there is no "repo root" -- data files listed
# in the .spec's `datas` are extracted to sys._MEIPASS at startup instead.
if getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    _BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG_PATH = _BASE_DIR / "config" / "default.yaml"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AIConfig(_Frozen):
    enabled: bool = False
    provider: str = "none"
    min_confidence_to_use: float = 0.75


class ExpectedCountConfig(_Frozen):
    assume_single_when_unknown: bool = False
    min_confidence_to_accept: float = 0.60
    scan_radius: int = 3
    max_sane_count: int = 500


class StatusConfig(_Frozen):
    oversupply_is_review: bool = False
    treat_blank_optional_as: str = "MISSING"
    na_tokens: list[str] = ["n/a", "na", "not applicable", "nil", "none", "-", "--"]
    low_confidence_review_threshold: float = 0.50


class ParsingConfig(_Frozen):
    max_values_per_cell: int = 500
    strip_enumeration: bool = True
    duplicates_are_invalid: bool = True


class PhoneValidationConfig(_Frozen):
    country: str = "IN"
    allowed_lengths: list[int] = [10]
    allow_country_code: bool = True
    allowed_first_digits: list[str] = ["6", "7", "8", "9"]


class AmountValidationConfig(_Frozen):
    currency_symbols: list[str] = ["₹", "Rs.", "Rs", "INR", "inr"]
    allow_indian_grouping: bool = True
    allow_negative: bool = False


class DateValidationConfig(_Frozen):
    formats: list[str] = [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d %b %Y",
        "%d %B %Y",
    ]
    dayfirst: bool = True


class NameValidationConfig(_Frozen):
    min_length: int = 2
    max_length: int = 80


class ValidationConfig(_Frozen):
    phone: PhoneValidationConfig = PhoneValidationConfig()
    amount: AmountValidationConfig = AmountValidationConfig()
    date: DateValidationConfig = DateValidationConfig()
    name: NameValidationConfig = NameValidationConfig()


class SecurityConfig(_Frozen):
    log_cell_values: bool = False
    redact_in_reports: bool = False


class ReportConfig(_Frozen):
    freeze_header_row: bool = True
    autofilter: bool = True


class Config(_Frozen):
    ai: AIConfig = AIConfig()
    expected_count: ExpectedCountConfig = ExpectedCountConfig()
    status: StatusConfig = StatusConfig()
    parsing: ParsingConfig = ParsingConfig()
    validation: ValidationConfig = ValidationConfig()
    security: SecurityConfig = SecurityConfig()
    report: ReportConfig = ReportConfig()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _read_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(
    override_path: Optional[str | Path] = None,
    overrides: Optional[dict[str, Any]] = None,
) -> Config:
    """Load the default config, optionally layering an override file and/or
    an in-memory overrides dict (deep-merged, in that order)."""
    data = _read_yaml(DEFAULT_CONFIG_PATH)

    if override_path is not None:
        override_file = Path(override_path)
        if not override_file.exists():
            raise FileNotFoundError(f"Config override file not found: {override_file}")
        data = _deep_merge(data, _read_yaml(override_file))

    if overrides:
        data = _deep_merge(data, overrides)

    return Config(**data)
