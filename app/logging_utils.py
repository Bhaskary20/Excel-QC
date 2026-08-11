"""Redaction-safe logging.

Hard rule for the whole codebase: no logger call may interpolate a raw
cell/response value directly. Wrap any such value in redact() first. This
is enforced mechanically by tests/test_no_value_logging.py (Phase 13) — do
not rely on discipline alone.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Optional

_ROOT_NAME = "excel_qc"
_configured = False


def _configure_root(verbose: bool = False) -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s", datefmt="%H:%M:%S")
    )
    root = logging.getLogger(_ROOT_NAME)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(handler)
    root.propagate = False
    _configured = True


def set_verbose(verbose: bool) -> None:
    _configure_root(verbose)
    logging.getLogger(_ROOT_NAME).setLevel(logging.DEBUG if verbose else logging.INFO)


def get_logger(name: str) -> logging.Logger:
    _configure_root()
    return logging.getLogger(f"{_ROOT_NAME}.{name}")


def redact(value: Any, cfg: Optional[object] = None) -> str:
    """Return a safe-to-log representation of a potentially confidential value.

    Only returns the raw value if cfg.security.log_cell_values is explicitly
    True (local debugging only). Otherwise returns a length-only placeholder
    so shape/size can still be diagnosed without exposing content.
    """
    if value is None:
        return "<none>"
    text = str(value)
    log_raw = False
    if cfg is not None:
        security = getattr(cfg, "security", None)
        log_raw = bool(getattr(security, "log_cell_values", False))
    if log_raw:
        return text
    return f"<redacted:len={len(text)}>"
