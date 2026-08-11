"""Phase 3 gate: the BUILD_PLAN.md worked-example table, plus the digit-guard
edge cases that make ₹2,50,000 and 10/08/2026 survive splitting."""

import pytest

from app.config import load_config
from app.models import FieldType
from app.value_splitter import NA_SENTINEL, split_values, strip_enumeration

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(scope="module")
def cfg():
    return load_config()


# (text, field_type, expected_tokens) -- straight from BUILD_PLAN.md Phase 3's table
TABLE_CASES = [
    ("9876543210, 9876543211, 9876543212", FieldType.PHONE,
     ["9876543210", "9876543211", "9876543212"]),
    ("9876543210\n9876543211\n9876543212", FieldType.PHONE,
     ["9876543210", "9876543211", "9876543212"]),
    ("1. 9876543210\n2. 9876543211", FieldType.PHONE,
     ["9876543210", "9876543211"]),
    ("9876543210;\n9876543211;", FieldType.PHONE,
     ["9876543210", "9876543211"]),
    ("₹2,50,000", FieldType.AMOUNT, ["₹2,50,000"]),
    ("₹2,50,000\n₹3,00,000", FieldType.AMOUNT, ["₹2,50,000", "₹3,00,000"]),
    ("₹2,50,000, ₹3,00,000", FieldType.AMOUNT, ["₹2,50,000", "₹3,00,000"]),
    ("10/08/2026", FieldType.DATE, ["10/08/2026"]),
    ("10/08/2026, 11/08/2026", FieldType.DATE, ["10/08/2026", "11/08/2026"]),
    ("H.No 12-3, Main Road, Nellore", FieldType.ADDRESS,
     ["H.No 12-3, Main Road, Nellore"]),
    ("17.3850, 78.4867", FieldType.COORDINATE, ["17.3850, 78.4867"]),
    ("km 12+300, km 14+500", FieldType.CHAINAGE, ["km 12+300", "km 14+500"]),
    ("", FieldType.PHONE, []),
    ("   ", FieldType.PHONE, []),
]


@pytest.mark.parametrize("text,field_type,expected", TABLE_CASES)
def test_split_values_table(cfg, text, field_type, expected):
    assert split_values(text, field_type, cfg) == expected


@pytest.mark.parametrize("na_text", ["N/A", "n/a", "Nil", "None", "-", "--", "Not Applicable"])
def test_na_tokens_return_sentinel(cfg, na_text):
    assert split_values(na_text, FieldType.PHONE, cfg) == [NA_SENTINEL]


def test_bulleted_names_are_cleaned(cfg):
    text = "• Rahul Sharma\n• Amit Kumar"
    assert split_values(text, FieldType.NAME, cfg) == ["Rahul Sharma", "Amit Kumar"]


def test_split_does_not_validate_just_tokenizes(cfg):
    # §7's mixed example: splitting yields all 4 raw tokens; validity is Phase 4's job.
    text = "9876543210\n9876543211\n9876\n9876543213"
    assert split_values(text, FieldType.PHONE, cfg) == [
        "9876543210", "9876543211", "9876", "9876543213"
    ]


def test_newline_wins_over_trailing_commas(cfg):
    text = "9876543210,\n9876543211,"
    assert split_values(text, FieldType.PHONE, cfg) == ["9876543210", "9876543211"]


def test_amount_with_rs_prefix_and_grouping_stays_single(cfg):
    assert split_values("Rs. 25,000", FieldType.AMOUNT, cfg) == ["Rs. 25,000"]


def test_document_reference_with_slashes_stays_single(cfg):
    text = "NH-16/2024/ROW-01"
    assert split_values(text, FieldType.DOCUMENT_REFERENCE, cfg) == [text]


def test_name_list_with_plain_commas(cfg):
    text = "Rahul Sharma, Amit Kumar, Rakesh Singh"
    assert split_values(text, FieldType.NAME, cfg) == ["Rahul Sharma", "Amit Kumar", "Rakesh Singh"]


def test_percentage_list_with_commas(cfg):
    assert split_values("25%, 30%, 45%", FieldType.PERCENTAGE, cfg) == ["25%", "30%", "45%"]


def test_strip_enumeration_variants():
    assert strip_enumeration("1. Rahul Sharma") == "Rahul Sharma"
    assert strip_enumeration("(1) Rahul Sharma") == "Rahul Sharma"
    assert strip_enumeration("1) Rahul Sharma") == "Rahul Sharma"
    assert strip_enumeration("a) Rahul Sharma") == "Rahul Sharma"
    assert strip_enumeration("• Rahul Sharma") == "Rahul Sharma"
    assert strip_enumeration("- Rahul Sharma") == "Rahul Sharma"
    assert strip_enumeration("iv) Rahul Sharma") == "Rahul Sharma"


def test_strip_enumeration_does_not_eat_bare_numbers_or_decimals():
    assert strip_enumeration("5") == "5"
    assert strip_enumeration("1.5") == "1.5"
    assert strip_enumeration("250000") == "250000"


def test_none_text_returns_empty(cfg):
    assert split_values(None, FieldType.PHONE, cfg) == []


def test_max_values_per_cell_guardrail():
    cfg = load_config(overrides={"parsing": {"max_values_per_cell": 3}})
    text = "\n".join(f"987654321{i}" for i in range(10))
    tokens = split_values(text, FieldType.PHONE, cfg)
    assert len(tokens) == 3


def test_pure_punctuation_tokens_are_dropped(cfg):
    text = "9876543210, --, 9876543211"
    assert split_values(text, FieldType.PHONE, cfg) == ["9876543210", "9876543211"]
