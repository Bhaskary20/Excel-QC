"""Streamlit GUI for the Excel response QC checker.

    streamlit run streamlit_app.py

Thin wrapper around the same pipeline main.py uses (read_cells ->
resolve_sheet -> run_qc_from_cells -> generate_report) -- no QC logic lives
here. Runs entirely locally: the uploaded response workbook and the
generated report are written only inside a TemporaryDirectory that's
deleted as soon as the run finishes, and the on-screen Status table is read
back from the generated report itself rather than recomputed, so it can
never drift from what's actually in the Excel file.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import openpyxl
import pandas as pd
import streamlit as st

import app.validators  # noqa: F401 -- import side effect activates real validators
from app.config import load_config
from app.excel_reader import read_cells
from app.qc_engine import run_qc_from_cells
from app.report_generator import generate_report
from app.row_matcher import resolve_sheet
from app.template_spec import SHEET_NAME

TEMPLATE_PATH = str(Path(__file__).resolve().parent / "template" / "Format.xlsx")
_STATUS_COLUMNS = ["RO", "Plaza", "PIU", "Status", "Remarks"]

st.set_page_config(page_title="Toll Plaza Response QC", layout="wide")
st.title("Toll Plaza Response QC")
st.caption(
    "Upload a client's filled-in response workbook to check it against the fixed NHAI template. "
    "Everything runs locally -- the uploaded file and the report never leave this machine."
)

uploaded = st.file_uploader("Response workbook (.xlsx)", type=["xlsx"])

if uploaded is not None:
    upload_key = (uploaded.name, uploaded.size)
    if st.session_state.get("upload_key") != upload_key:
        # A different file was uploaded -- drop any previous run's results
        # rather than risk showing stale results next to the new filename.
        st.session_state.pop("status_df", None)
        st.session_state.pop("report_bytes", None)
        st.session_state.pop("summary", None)
        st.session_state["upload_key"] = upload_key

    if st.button("Run QC", type="primary"):
        with st.spinner("Checking response against the template..."):
            with tempfile.TemporaryDirectory() as tmpdir:
                response_path = Path(tmpdir) / "response.xlsx"
                response_path.write_bytes(uploaded.getvalue())
                output_path = Path(tmpdir) / "QC_Report.xlsx"

                try:
                    cfg = load_config()
                    template_cells = read_cells(TEMPLATE_PATH)
                    response_cells = read_cells(str(response_path))
                except Exception as e:  # noqa: BLE001 -- mirrors main.py's file-open error handling
                    st.error(f"Could not open the uploaded file: {e}")
                    st.stop()

                response_sheet = resolve_sheet(response_cells, SHEET_NAME)
                if response_sheet is None:
                    sheets = sorted({c.sheet for c in response_cells})
                    st.error(
                        f"Could not find sheet {SHEET_NAME!r} in the uploaded file, and it has "
                        f"multiple sheets so the correct one can't be guessed. Sheets found: {sheets}"
                    )
                    st.stop()

                try:
                    run = run_qc_from_cells(
                        template_cells, response_cells, cfg, TEMPLATE_PATH, str(response_path)
                    )
                    generate_report(run, str(output_path), cfg)
                except Exception:  # noqa: BLE001 -- never surface a raw traceback in the GUI
                    st.error("An unexpected problem occurred while processing the workbook.")
                    st.stop()

                report_bytes = output_path.read_bytes()

                wb = openpyxl.load_workbook(output_path, data_only=True)
                status_ws = wb["Status"]
                status_rows = [
                    dict(zip(_STATUS_COLUMNS, row))
                    for row in status_ws.iter_rows(min_row=2, values_only=True)
                    if row[1] is not None  # Plaza column blank -> no more data
                ]

                st.session_state["status_df"] = pd.DataFrame(status_rows, columns=_STATUS_COLUMNS)
                st.session_state["report_bytes"] = report_bytes
                st.session_state["summary"] = run.workbook_summary

    if "status_df" in st.session_state:
        summary = st.session_state["summary"]
        completeness = summary.overall_completeness
        completeness_str = f"{completeness:.2%}" if completeness is not None else "N/A"

        col1, col2, col3 = st.columns(3)
        col1.metric("Rows checked", summary.total_rows)
        col2.metric("Overall completeness", completeness_str)
        col3.metric("Consistency findings", summary.total_consistency_findings)

        status_counts = st.session_state["status_df"]["Status"].value_counts()
        st.write("**Status breakdown:** " + ", ".join(f"{count} {label}" for label, count in status_counts.items()))

        st.subheader("Status")
        st.dataframe(st.session_state["status_df"], width="stretch", hide_index=True)

        st.download_button(
            "Download full report (QC_Report.xlsx)",
            data=st.session_state["report_bytes"],
            file_name="QC_Report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
