# Toll Plaza Response QC

Checks a client's filled-in Excel response against the fixed NHAI toll-plaza
contract-details template (`template/Format.xlsx`) and grades every field
COMPLETE / PARTIAL / MISSING / INVALID / REVIEW / NOT_APPLICABLE, producing a
6-sheet `QC_Report.xlsx` with a primary Status sheet (RO | Plaza | PIU |
Status | Remarks) matching NHAI's own PIU-response tracker format.

See `BUILD_PLAN.md` for the full technical design, validation rules, and
project history.

## Confidentiality -- read this before deploying anywhere

**This tool is designed to run entirely on your own machine. No file, cell
value, or derived text is ever meant to leave it.** The response workbooks
it processes contain real client data for an active fraud investigation.

- Do **not** deploy this to Streamlit Community Cloud, or any other
  third-party/public hosting service. That would send confidential data to
  infrastructure outside your control.
- Run it locally (`streamlit run streamlit_app.py`) or on infrastructure
  your organization controls and trusts with this data.
- `.streamlit/config.toml` already binds the local server to `localhost`
  only and disables Streamlit's telemetry, so nothing is reachable from
  another machine on your network and no usage data is phoned home.
- `desktop_app.py` has no server or network exposure at all -- it's a
  native window with direct file-system access, arguably the safer of the
  two GUIs if that matters to your deployment.
- Never commit a real response `.xlsx` file. `.gitignore` already blocks
  every `.xlsx`/`.xls` in the repo except the blank template
  (`template/Format.xlsx`) -- keep it that way.

## Setup

Requires Python 3.12+ (developed and tested on 3.12.6) and git.

```bash
git clone <this-repo-url>
cd "excel automation"

python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Running it

### Desktop app

```bash
python desktop_app.py
```

A native window (CustomTkinter, no browser involved). Select a response
`.xlsx`, click **Run QC**, review the Status table, then **Download Full
Report** to save `QC_Report.xlsx` wherever you like via the native save
dialog.

### Browser GUI

```bash
streamlit run streamlit_app.py
```

Opens in your browser at `http://localhost:8501`. Same flow as the desktop
app -- upload a response workbook, click **Run QC**, review the Status
table, and download the full report.

### Command line

```bash
python main.py --response "path/to/client_reply.xlsx" --output "output/QC_Report.xlsx"
```

Run `python main.py --help` for the full list of flags (`--strict`,
`--dump-json`, `--config`, etc.). `--template` defaults to the committed
`template/Format.xlsx` and normally never needs to be passed.

## Running the tests

```bash
pytest
```

354 tests as of this writing, covering every module against both synthetic
fixtures and the rules documented in `BUILD_PLAN.md`.

## Project layout

```
app/                 the QC engine (template spec, parsing, validation, reporting)
config/default.yaml  tunable rules (phone/date formats, NA tokens, etc.)
template/Format.xlsx the fixed, blank NHAI template (the only .xlsx committed)
tests/                pytest suite
main.py               CLI entry point
streamlit_app.py      browser GUI entry point
desktop_app.py         desktop GUI entry point (CustomTkinter)
output/                generated reports land here (gitignored)
```
