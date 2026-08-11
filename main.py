"""CLI entry point for the Excel response QC checker.

    python main.py --response client_reply.xlsx --output output/QC_Report.xlsx

--template defaults to the fixed, committed template/Format.xlsx.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from openpyxl.utils.exceptions import InvalidFileException

import app.validators  # noqa: F401 -- import side effect activates real validators
from app.config import load_config
from app.excel_reader import CellRecord, read_cells
from app.logging_utils import get_logger, set_verbose
from app.models import QCRun
from app.qc_engine import run_qc_from_cells
from app.report_generator import generate_report
from app.row_matcher import resolve_sheet
from app.template_spec import SHEET_NAME

DEFAULT_TEMPLATE = str(Path(__file__).resolve().parent / "template" / "Format.xlsx")
DEFAULT_OUTPUT = "output/QC_Report.xlsx"

log = get_logger("main")


class _JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Excel response QC checker for the NHAI toll-plaza contract-details template.",
    )
    parser.add_argument("--template", default=DEFAULT_TEMPLATE, help="path to the template workbook (default: the committed template/Format.xlsx)")
    parser.add_argument("--response", required=True, help="path to the client's filled-in response workbook")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"path to write QC_Report.xlsx (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--config", default=None, metavar="PATH", help="path to a config override YAML file")
    parser.add_argument("--strict", action="store_true", help="exit 1 unless every row is COMPLETE")
    parser.add_argument("--quiet", action="store_true", help="print only the final summary line")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging and full tracebacks on error")
    parser.add_argument("--dump-json", default=None, metavar="PATH", help="also write the full QC result as JSON to PATH")
    return parser.parse_args(argv)


def _load_cells(path: str, label: str) -> Optional[list[CellRecord]]:
    """Returns None (after printing a clear message) on any failure, rather
    than calling sys.exit() itself -- that keeps main() a plain function
    that always returns an int, which is what makes it callable directly
    from tests instead of only via a subprocess."""
    file_path = Path(path)
    if not file_path.exists():
        print(f"Error: {label} not found: {path}", file=sys.stderr)
        return None
    if file_path.suffix.lower() == ".xls":
        print(f"Error: {label} is a legacy .xls file ({path}). Please re-save it as .xlsx and try again.", file=sys.stderr)
        return None
    try:
        return read_cells(str(file_path))
    except InvalidFileException as e:
        print(f"Error: {label} is not a valid Excel workbook ({path}): {e}", file=sys.stderr)
        return None
    except Exception as e:  # noqa: BLE001 -- last resort: never let a bad file produce a raw traceback
        print(f"Error: could not open {label} ({path}): {e}", file=sys.stderr)
        print("If the file is password-protected or corrupted, fix that and try again.", file=sys.stderr)
        return None


def _print_summary(run: QCRun, output_path: str, quiet: bool) -> None:
    s = run.workbook_summary
    completeness_str = f"{s.overall_completeness:.2%}" if s.overall_completeness is not None else "N/A"

    if quiet:
        print(f"Excel QC completed. Overall completeness: {completeness_str}. Report: {output_path}")
        return

    print("Excel QC completed.")
    print()
    print(f"Rows checked: {s.total_rows}")
    print(f"Cells checked: {s.total_cells_checked}")
    print()
    print(f"Expected slots: {s.total_expected_slots:,}")
    print(f"Valid slots: {s.total_valid_slots:,}")
    print(f"Missing slots: {s.total_missing_slots:,}")
    print(f"Invalid slots: {s.total_invalid_slots:,}")
    print()
    print(f"Complete cells: {s.complete_cells}")
    print(f"Partial cells: {s.partial_cells}")
    print(f"Missing cells: {s.missing_cells}")
    print(f"Invalid cells: {s.invalid_cells}")
    print(f"Review cells: {s.review_cells}")
    print(f"Not applicable cells: {s.not_applicable_cells}")
    print()
    print(f"Complete rows: {s.complete_rows}")
    print(f"Partial rows: {s.partial_rows}")
    print(f"Missing rows: {s.missing_rows}")
    print(f"Review rows: {s.review_rows}")
    print()
    print(f"Consistency findings: {s.total_consistency_findings}")
    print()
    print(f"Overall completeness: {completeness_str}")
    print()
    print("Report:")
    print(output_path)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    set_verbose(args.verbose)

    try:
        cfg = load_config(override_path=args.config)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    template_cells = _load_cells(args.template, "template")
    if template_cells is None:
        return 2

    response_cells = _load_cells(args.response, "response")
    if response_cells is None:
        return 2

    response_sheet = resolve_sheet(response_cells, SHEET_NAME)
    if response_sheet is None:
        response_sheets = sorted({c.sheet for c in response_cells})
        print(
            f"Error: could not find sheet {SHEET_NAME!r} in the response, and the response has "
            "multiple sheets so the correct one can't be guessed.",
            file=sys.stderr,
        )
        print(f"Sheets found: {response_sheets}", file=sys.stderr)
        return 2

    try:
        if Path(args.template).resolve() == Path(args.response).resolve():
            print(
                "Warning: the response file is identical to the template -- "
                "did you mean to attach the client's filled-in copy?",
                file=sys.stderr,
            )
    except OSError:
        pass  # path resolution is best-effort; never block a real run over it

    try:
        run = run_qc_from_cells(template_cells, response_cells, cfg, args.template, args.response)
        generate_report(run, args.output, cfg)
    except Exception:
        if args.verbose:
            raise
        print("Error: an unexpected problem occurred while processing the workbooks.", file=sys.stderr)
        print("Re-run with -v/--verbose for the full error.", file=sys.stderr)
        return 2

    if args.dump_json:
        with open(args.dump_json, "w", encoding="utf-8") as f:
            json.dump(asdict(run), f, cls=_JSONEncoder, indent=2, ensure_ascii=False)

    _print_summary(run, args.output, args.quiet)

    if args.strict:
        s = run.workbook_summary
        if s.missing_rows or s.invalid_rows or s.review_rows or s.partial_rows:
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
