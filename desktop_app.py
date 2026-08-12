"""Desktop GUI for the Excel response QC checker.

    python desktop_app.py

Thin wrapper around the same pipeline main.py and streamlit_app.py use
(read_cells -> resolve_sheet -> run_qc_from_cells -> generate_report) --
no QC logic lives here. Runs entirely locally: nothing is written outside a
TemporaryDirectory that's deleted as soon as the app closes, and the file
you pick to save is written directly from the bytes generate_report
produced -- no network calls, no telemetry, nothing leaves this machine.
"""

from __future__ import annotations

import queue
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Optional

import customtkinter as ctk

import app.validators  # noqa: F401 -- import side effect activates real validators
from app.config import load_config
from app.excel_reader import read_cells
from app.qc_engine import run_qc_from_cells
from app.report_generator import generate_report
from app.row_matcher import resolve_sheet
from app.template_spec import SHEET_NAME

import openpyxl

TEMPLATE_PATH = str(Path(__file__).resolve().parent / "template" / "Format.xlsx")

# ---- palette ---------------------------------------------------------------
BG = "#0d1117"
CARD = "#161b22"
CARD_BORDER = "#26303c"
ACCENT = "#10b981"
ACCENT_HOVER = "#0d9668"
DANGER = "#ef4444"
TEXT_PRIMARY = "#f0f6fc"
TEXT_SECONDARY = "#8b96a5"
STATUS_PARTIAL = "#f59e0b"
STATUS_NORESPONSE = "#ef4444"
STATUS_FULL = "#10b981"

_STATUS_COLORS = {
    "Full Response": STATUS_FULL,
    "Partial Response": STATUS_PARTIAL,
    "No Response": STATUS_NORESPONSE,
}

ctk.set_appearance_mode("dark")


class QCApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Toll Plaza Response QC")
        self.geometry("1180x780")
        self.minsize(980, 640)
        self.configure(fg_color=BG)

        self._response_path: Optional[Path] = None
        self._report_bytes: Optional[bytes] = None
        self._work_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()

        self._build_header()
        self._build_upload_card()
        self._build_results_area()

    # ---- layout ------------------------------------------------------------

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=32, pady=(28, 12))

        ctk.CTkLabel(
            header, text="Toll Plaza Response QC",
            font=ctk.CTkFont(family="Segoe UI", size=28, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w")

        ctk.CTkLabel(
            header,
            text="Check a client's filled-in response against the fixed NHAI template.  "
                 "Everything runs locally — nothing leaves this machine.",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=TEXT_SECONDARY,
        ).pack(anchor="w", pady=(2, 0))

    def _build_upload_card(self) -> None:
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14, border_width=1, border_color=CARD_BORDER)
        card.pack(fill="x", padx=32, pady=(0, 18))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=24, pady=20)
        inner.grid_columnconfigure(0, weight=1)

        self._file_label = ctk.CTkLabel(
            inner, text="No response workbook selected",
            font=ctk.CTkFont(family="Segoe UI", size=14),
            text_color=TEXT_SECONDARY, anchor="w",
        )
        self._file_label.grid(row=0, column=0, sticky="w")

        self._browse_btn = ctk.CTkButton(
            inner, text="Select .xlsx", width=140, height=38, corner_radius=10,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=CARD_BORDER, hover_color="#334155", text_color=TEXT_PRIMARY,
            command=self._on_browse,
        )
        self._browse_btn.grid(row=0, column=1, padx=(12, 0))

        self._run_btn = ctk.CTkButton(
            inner, text="Run QC", width=140, height=38, corner_radius=10,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#04120c",
            state="disabled", command=self._on_run,
        )
        self._run_btn.grid(row=0, column=2, padx=(10, 0))

        self._progress = ctk.CTkProgressBar(inner, mode="indeterminate", fg_color=CARD_BORDER, progress_color=ACCENT)
        self._status_label = ctk.CTkLabel(
            inner, text="", font=ctk.CTkFont(family="Segoe UI", size=12), text_color=TEXT_SECONDARY, anchor="w",
        )
        # progress + status live below the buttons, gridded in on demand

    def _build_results_area(self) -> None:
        self._results_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._results_frame.pack(fill="both", expand=True, padx=32, pady=(0, 24))

        self._metrics_row = ctk.CTkFrame(self._results_frame, fg_color="transparent")
        self._metrics_row.pack(fill="x", pady=(0, 14))

        self._metric_cards = {}
        for key, label in [("rows", "Rows Checked"), ("completeness", "Overall Completeness"), ("findings", "Consistency Findings")]:
            self._metric_cards[key] = self._make_metric_card(self._metrics_row, label)

        self._breakdown_label = ctk.CTkLabel(
            self._results_frame, text="", font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=TEXT_SECONDARY, anchor="w",
        )
        self._breakdown_label.pack(fill="x", pady=(0, 14))

        table_card = ctk.CTkFrame(self._results_frame, fg_color=CARD, corner_radius=14, border_width=1, border_color=CARD_BORDER)
        table_card.pack(fill="both", expand=True)

        self._configure_treeview_style()
        columns = ("ro", "plaza", "piu", "status", "remarks")
        self._tree = ttk.Treeview(table_card, columns=columns, show="headings", style="QC.Treeview")
        headings = {"ro": "RO", "plaza": "Plaza", "piu": "PIU", "status": "Status", "remarks": "Remarks"}
        widths = {"ro": 110, "plaza": 140, "piu": 140, "status": 130, "remarks": 520}
        for col in columns:
            self._tree.heading(col, text=headings[col])
            self._tree.column(col, width=widths[col], anchor="w")
        self._tree.tag_configure("Partial Response", foreground=STATUS_PARTIAL)
        self._tree.tag_configure("No Response", foreground=STATUS_NORESPONSE)
        self._tree.tag_configure("Full Response", foreground=STATUS_FULL)

        vsb = ttk.Scrollbar(table_card, orient="vertical", command=self._tree.yview, style="QC.Vertical.TScrollbar")
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True, padx=(2, 0), pady=2)
        vsb.pack(side="right", fill="y", pady=2)

        self._save_btn = ctk.CTkButton(
            self._results_frame, text="Download Full Report (QC_Report.xlsx)", height=42, corner_radius=10,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#04120c",
            state="disabled", command=self._on_save,
        )
        self._save_btn.pack(fill="x", pady=(14, 0))

        # Nothing to show yet -- hide the whole results block until a run completes.
        self._results_frame.pack_forget()

    def _make_metric_card(self, parent: ctk.CTkFrame, label: str) -> dict:
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14, border_width=1, border_color=CARD_BORDER)
        card.pack(side="left", fill="both", expand=True, padx=(0, 12))
        value_lbl = ctk.CTkLabel(card, text="—", font=ctk.CTkFont(family="Segoe UI", size=30, weight="bold"), text_color=TEXT_PRIMARY)
        value_lbl.pack(padx=20, pady=(16, 0), anchor="w")
        ctk.CTkLabel(card, text=label, font=ctk.CTkFont(family="Segoe UI", size=12), text_color=TEXT_SECONDARY).pack(padx=20, pady=(0, 14), anchor="w")
        return {"card": card, "value": value_lbl}

    def _configure_treeview_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "QC.Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT_PRIMARY,
            borderwidth=0, rowheight=30, font=("Segoe UI", 11),
        )
        style.configure(
            "QC.Treeview.Heading", background="#0d1117", foreground=TEXT_SECONDARY,
            borderwidth=0, font=("Segoe UI", 11, "bold"), relief="flat",
        )
        style.map("QC.Treeview", background=[("selected", "#1f2b3a")])
        style.map("QC.Treeview.Heading", background=[("active", "#0d1117")])
        style.layout("QC.Vertical.TScrollbar", style.layout("Vertical.TScrollbar"))
        style.configure("QC.Vertical.TScrollbar", background=CARD_BORDER, troughcolor=CARD, borderwidth=0, arrowsize=12)

    # ---- interaction ---------------------------------------------------------

    def _on_browse(self) -> None:
        path = filedialog.askopenfilename(title="Select response workbook", filetypes=[("Excel workbook", "*.xlsx")])
        if not path:
            return
        self._response_path = Path(path)
        self._file_label.configure(text=self._response_path.name, text_color=TEXT_PRIMARY)
        self._run_btn.configure(state="normal")
        self._results_frame.pack_forget()
        self._save_btn.configure(state="disabled")

    def _set_busy(self, busy: bool, message: str = "") -> None:
        if busy:
            self._progress.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(14, 0))
            self._status_label.configure(text=message)
            self._status_label.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
            self._progress.start()
            self._run_btn.configure(state="disabled")
            self._browse_btn.configure(state="disabled")
        else:
            self._progress.stop()
            self._progress.grid_forget()
            self._status_label.grid_forget()
            self._run_btn.configure(state="normal")
            self._browse_btn.configure(state="normal")

    def _on_run(self) -> None:
        if self._response_path is None:
            return
        self._set_busy(True, "Checking response against the template…")
        thread = threading.Thread(target=self._run_qc_worker, args=(self._response_path,), daemon=True)
        thread.start()
        self.after(120, self._poll_worker)

    def _run_qc_worker(self, response_path: Path) -> None:
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = Path(tmpdir) / "QC_Report.xlsx"
                cfg = load_config()
                template_cells = read_cells(TEMPLATE_PATH)
                response_cells = read_cells(str(response_path))

                response_sheet = resolve_sheet(response_cells, SHEET_NAME)
                if response_sheet is None:
                    sheets = sorted({c.sheet for c in response_cells})
                    self._work_queue.put(("error", f"Could not find sheet {SHEET_NAME!r} in the file. Sheets found: {sheets}"))
                    return

                run = run_qc_from_cells(template_cells, response_cells, cfg, TEMPLATE_PATH, str(response_path))
                generate_report(run, str(output_path), cfg)
                report_bytes = output_path.read_bytes()

                wb = openpyxl.load_workbook(output_path, data_only=True)
                status_rows = [
                    row[:5] for row in wb["Status"].iter_rows(min_row=2, values_only=True) if row[1] is not None
                ]
                summary = run.workbook_summary
                self._work_queue.put(("done", {
                    "report_bytes": report_bytes,
                    "status_rows": status_rows,
                    "rows": summary.total_rows,
                    "completeness": summary.overall_completeness,
                    "findings": summary.total_consistency_findings,
                }))
        except Exception:  # noqa: BLE001 -- never let a raw traceback surface in the GUI
            self._work_queue.put(("error", "An unexpected problem occurred while processing the workbook."))

    def _poll_worker(self) -> None:
        try:
            kind, payload = self._work_queue.get_nowait()
        except queue.Empty:
            self.after(120, self._poll_worker)
            return

        self._set_busy(False)
        if kind == "error":
            self._status_label.configure(text=str(payload), text_color=DANGER)
            self._status_label.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
            return

        self._render_results(payload)

    def _render_results(self, payload: dict) -> None:
        self._report_bytes = payload["report_bytes"]

        completeness = payload["completeness"]
        completeness_str = f"{completeness:.2%}" if completeness is not None else "N/A"
        self._metric_cards["rows"]["value"].configure(text=str(payload["rows"]))
        self._metric_cards["completeness"]["value"].configure(text=completeness_str)
        self._metric_cards["findings"]["value"].configure(text=str(payload["findings"]))

        counts: dict[str, int] = {}
        for row in self._tree.get_children():
            self._tree.delete(row)
        for ro, plaza, piu, status, remarks in payload["status_rows"]:
            counts[status] = counts.get(status, 0) + 1
            self._tree.insert("", "end", values=(ro, plaza, piu, status, remarks or ""), tags=(status,))

        self._breakdown_label.configure(text="Status breakdown:  " + "   ".join(f"{v} {k}" for k, v in counts.items()))

        self._results_frame.pack(fill="both", expand=True, padx=32, pady=(0, 24))
        self._save_btn.configure(state="normal")

    def _on_save(self) -> None:
        if self._report_bytes is None:
            return
        dest = filedialog.asksaveasfilename(
            title="Save QC report", defaultextension=".xlsx",
            initialfile="QC_Report.xlsx", filetypes=[("Excel workbook", "*.xlsx")],
        )
        if not dest:
            return
        Path(dest).write_bytes(self._report_bytes)


if __name__ == "__main__":
    app = QCApp()
    app.mainloop()
