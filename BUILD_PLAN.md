# Toll Plaza Response QC — Build Plan (v2, template-driven)

> **Confidential.** All processing is local. No file, cell value, or derived text ever leaves this machine.

This plan is written against the **actual** template, `template/Format.xlsx`. v1 of this plan assumed an unknown template and specified heuristic detectors to infer structure; that guesswork is now unnecessary and has been removed. The template is fixed and identical on every send — its structure is hardcoded as a declarative spec, and all remaining intelligence goes into reading **messy client responses**.

---

## 1. The template, exactly as it is

**File:** `template/Format.xlsx` · **Sheets:** `Instructions`, `Data Sheet for UP STF`

### 1.1 Sheet `Instructions` — static reference, not data

Rows 6–20, a two-column dictionary (`A` = Column Name, `B` = Instructions). We do not parse this at runtime; we have transcribed its rules into §3 below. It is worth reading once because it is the authority on several QC rules:

| Instruction row | Rule it establishes |
|---|---|
| Exact Location of Plaza | Format = `"Village name as per Fee Notification" + "Chainage" + "City name" + "Pincode"` — **4 components** |
| Plaza Type | Controlled vocabulary: `Public Funded / BOT / TOT / Invit / MLFF` |
| EQ / Regular | Controlled vocabulary: `EQ (3 months)` or `Regular (1 Year)` |
| Contract Start & End Date | Format `DD/MM/YYYY - DD/MM/YYYY`, **and** "contract end date of previous agency should match with the contract start date of the new agency" — a chain-continuity rule |
| Contact Number | "Provide valid mobile number (of Toll manager)" |
| Note (row 4) | "In cases where additional agencies are associated with a Toll Plaza, please add the additional agency details **below the provided fields**" — so the 6 slots are a **soft cap**, not a hard limit |

### 1.2 Sheet `Data Sheet for UP STF` — the graded sheet

- Row 1: title, merged `A1:S1`
- Row 2: headers, `A2:S2` (19 columns)
- Rows 3–117: **115 plaza rows**, one plaza per row
- `freeze_panes = A3`

> The sheet name says "UP STF" but the data spans 20 ROs nationally (Bhopal, Gujarat, Ranchi, Chandigarh, …). Ignore the name's implication; match the sheet by its exact string.

### 1.3 Column map — the single source of truth

| Col | Header | Role | Type | Cardinality |
|---|---|---|---|---|
| A | S.No | **KEY** (pre-filled) | INTEGER | 1 |
| B | Plaza Code | KEY (pre-filled, **unreliable**) | TEXT | 1 |
| C | Plaza Name | **KEY** (pre-filled, unique) | TEXT | 1 |
| D | RO | KEY (pre-filled) | TEXT | 1 |
| E | PIU | KEY (pre-filled) | TEXT | 1 |
| F | Plaza - Village, Location | INPUT | COMPOSITE_LOCATION | 1 |
| G | Plaza Type | INPUT | ENUM | 1 |
| H | Agency name | INPUT | TEXT | **N (anchor)** |
| I | EQ (3 months)/ Regular (1 year) | INPUT | ENUM | N |
| J | Contract Start & End date | INPUT | DATE_RANGE | N |
| K | Name of Toll Plaza Manager | INPUT | NAME | N |
| L | Contact of Toll Manager | INPUT | PHONE | N |
| M | Address of Toll Agency | INPUT | ADDRESS | N |
| N | Supervision Consultant (AE/IE) name and address | INPUT | TEXT | N |
| O | Team Leader name (AE/IE) | INPUT | NAME | N |
| P | HTMS / Toll Expert | INPUT | TEXT | N |
| Q | Per Day Average Traffic Count | INPUT | NUMBER | N |
| R | Average Traffic Count of Exempted vehicles | INPUT | NUMBER | N |
| S | Remarks | INPUT (**optional**) | TEXT | 1 |

**Row keys — verified against the real file:**
- `A` (S.No) is contiguous `1..115` → **primary key**
- `C` (Plaza Name) is **unique across all 115 rows** → verification key
- `B` (Plaza Code) is **not usable as a key**: 2 rows blank (rows 104, 105), 2 rows literally `"-"` (rows 25, 96)

### 1.4 The scaffold — the most important structural fact

Every cell in `H..R`, in all 115 rows, ships pre-filled with **exactly 6 numbered slots**:

```
Columns I, K, L, M, N, O, P, Q, R:
  "  1. \n  2. \n  3.\n  4. \n  5.\n  6."

Column H (agency name) carries placeholder text:
  "  1. Agency \n  2. Agency \n  3. Agency \n  4. Agency\n  5. Agency \n  6. Agency"

Column J (dates) carries a format hint:
  "  1. From (dd/mm/yyyy ) - To (dd/mm/yyyy) \n  2. From (dd/mm/yyyy ) - To (dd/mm/yyyy) \n  ... 6. ..."
```

Note the template's own whitespace is already irregular — leading two spaces, `1. ` with a trailing space but `3.` without. Client responses will be worse.

`F`, `G`, and `S` ship **empty** (no scaffold) — they are single-value-per-row fields.

---

## 2. What this template means for the engine

Five consequences drive the whole design. Everything else is plumbing.

### 2.1 Scaffold is not data

An untouched cell contains 6 numbered markers and **zero** information. A naive splitter reports "6 values provided"; the truth is **MISSING**. Same for the placeholder words: `Agency` in column H and `From (dd/mm/yyyy ) - To (dd/mm/yyyy)` in column J are template furniture, not responses.

**This is the single highest-value rule in the system.** Get it wrong and a completely blank submission scores 100%.

### 2.2 Parsing must be slot-aware, not list-aware

Values must be parsed into `{slot_number → value}`, never a flat list. Slot identity is what makes cross-column comparison meaningful: slot 3 in column H (the agency) is the *same contract* as slot 3 in column L (that agency's phone number). A flat list destroys that link the moment any slot is left blank in the middle.

### 2.3 N is per-row and anchored on column H

The number of contracts a plaza had is **not fixed** — it varies per plaza, and the Instructions sheet explicitly permits exceeding 6. So:

```
N(row) = number of filled agency slots in column H
```

Every other slotted column (`I..R`) is then expected to have exactly `N` filled slots. If H is itself empty, the row is MISSING wholesale and N is undefined.

### 2.4 Cross-column consistency is the primary finding

This is what the tool is *for*. For each row: if H lists 4 agencies but L has only 2 phone numbers, the finding is not a vague "60% complete" — it is:

> Row 12 (Plaza `SEHATGANJ`): 4 agencies declared; `Contact of Toll Manager` missing at slots **3, 4**.

Per-slot, per-column, actionable.

### 2.5 Identity columns are immutable

`A..E` are pre-filled by NHAI. If a response's values differ from the template's, the client has edited, re-sorted, or misaligned the sheet — every downstream comparison for that row is suspect. Flag as REVIEW rather than silently grading it.

---

## 3. Validation rules per column

| Col | Type | Valid | Invalid / flagged |
|---|---|---|---|
| F | COMPOSITE_LOCATION | Free text; **warn** if fewer than 4 comma/plus-separated components (village + chainage + city + pincode), or if no 6-digit pincode is present | empty, or still scaffold |
| G | ENUM | One of `Public Funded`, `BOT`, `TOT`, `InvIT`, `MLFF` (case/spacing-insensitive; accept `Invit`/`INVIT`) | anything else → INVALID, near-miss → REVIEW |
| H | TEXT | ≥3 chars, contains a letter | the literal word `Agency` → **scaffold, not data** |
| I | ENUM | Matches `EQ` or `Regular` (accept `EQ (3 months)`, `3 months`, `Regular (1 Year)`, `1 year`) | anything else |
| J | DATE_RANGE | Two dates, `DD/MM/YYYY - DD/MM/YYYY`. Accept `to`/`–`/`—` as separators. Both dates must parse, `start <= end`, and both should fall within `01/01/2021 – 14/01/2026` | `From (dd/mm/yyyy ) - To (dd/mm/yyyy)` → scaffold; single date → INVALID; out-of-window → REVIEW |
| K, O | NAME | 2–80 chars, letters/space/`.`/`'`/`-`, Unicode-aware (Indian-script names must pass) | pure digits, punctuation only |
| L | PHONE | 10 digits after stripping `+91`/`0091`/`0`/spaces/`-`/`()`; must start `6-9` | wrong length, non-digits, landline formats → INVALID with a shape reason |
| M | ADDRESS | ≥10 chars, contains a letter | too short |
| N, P | TEXT | ≥3 chars, contains a letter | — |
| Q, R | NUMBER | Positive integer after stripping `,` and units (`veh`, `PCU`, `/day`) | non-numeric, negative |
| S | TEXT (optional) | Any non-empty | never MISSING — optional |

**Cross-slot rules (per row):**
- **J chain continuity** — for slots ordered by start date, `end(k)` should equal `start(k+1)` (tolerance: ±1 day, to allow "ends 31/03, starts 01/04"). Violations → REVIEW with the gap/overlap described.
- **J window coverage** — the union of contract ranges should cover `01/01/2021 – 14/01/2026`. Gaps → REVIEW.
- **L duplicates** — the same phone for every agency is suspicious → REVIEW, not INVALID.

---

## 4. Reading messy responses

The client will not respect the scaffold's formatting. The parser must absorb all of this:

| What the client sends | How to read it |
|---|---|
| `1. ABC Ltd` / `1.ABC Ltd` / `1 . ABC Ltd` / `1) ABC Ltd` / `(1) ABC Ltd` | slot 1 = `ABC Ltd` |
| `1. ABC Ltd, 2. DEF Ltd` on one line | slots 1, 2 — numbering wins over line breaks |
| `ABC Ltd, DEF Ltd` (no numbering) | positional fallback → slots 1, 2 |
| `ABC Ltd⏎DEF Ltd` (no numbering) | positional fallback → slots 1, 2 |
| slots 1, 2, 4 filled; 3 blank | slot 3 explicitly absent — **preserve the gap** |
| slots 7, 8 added beyond the scaffold | accept; N grows past 6 |
| `9876543210 / 9876543211` | two values (slash separator, PHONE only) |
| `₹2,50,000` in a NUMBER column | one value — never split on digit-internal commas |
| `10/08/2026` in a DATE column | one value — never split on `/` |
| non-breaking spaces, zero-width chars, `\r\n`, trailing whitespace | normalized away before parsing |
| `N/A`, `NA`, `Nil`, `-`, `Not Applicable` | NOT_APPLICABLE, not a value |

**Parsing order (`slot_parser.py`):**

1. **Normalize** — NBSP→space, strip zero-width, `\r\n`/`\r`→`\n`, collapse 3+ blank lines, trim.
2. **NA check** — whole cell matches an NA token → return the NA sentinel.
3. **Scaffold check** — strip all numbering; if every remaining slot is empty **or** equals a known placeholder for that column, return "scaffold, unfilled" → MISSING.
4. **Numbered parse** — find markers `^\s*(\d{1,2})\s*[.)\-:]\s*` (multiline). If ≥2 found, slice the text between consecutive markers and key by the parsed number. This handles out-of-order and skipped numbers.
5. **Positional fallback** — no numbering: split on newline, then `;`, then type-permitted `,` / `/` (using the same digit-guard as v1: a comma between two digits is a thousands separator, not a separator). Assign slots `1..n` in order.
6. **Per-slot cleanup** — strip the marker, quotes, trailing separator punctuation; drop values that are pure punctuation; map placeholder text to empty.
7. **Cap** — refuse absurd slot numbers (>50) and absurd value counts; flag as REVIEW.

---

## 5. Status model

Unchanged from v1 — `COMPLETE / PARTIAL / MISSING / INVALID / REVIEW / NOT_APPLICABLE` — but now evaluated at **three** levels.

### 5.1 Cell level (one column of one row)

Given `N` (row anchor), `D` (slots filled), `V` (valid), `I` (invalid):

| # | Condition | Status | Completeness |
|---|---|---|---|
| 1 | Cell is unmodified scaffold, or empty | `MISSING` (`NOT_APPLICABLE` if column is optional) | 0.0 |
| 2 | Cell is an NA token | `NOT_APPLICABLE` | — |
| 3 | Row anchor `N == 0` (no agencies declared) | `MISSING` | 0.0 |
| 4 | `D > 0` and `V == 0` | `INVALID` | 0.0 |
| 5 | `V >= N` | `COMPLETE` | 1.0 |
| 6 | `0 < V < N` | `PARTIAL` | `V / N` |
| 7 | Identity column differs from template | `REVIEW` | — |

`missing_count = max(N - V, 0)` — computed from **valid**, not detected. An invalid value does not fill its slot.

### 5.2 Row level (one plaza)

- `N` = agency count from column H
- Per-column slot-gap list: which slot numbers are missing in each column
- Row status = worst cell status, with `REVIEW` if identity columns were altered
- Row completeness = `Σ valid across slotted columns / (N × number of slotted columns)`

### 5.3 Sheet / workbook level

Aggregate as in v1: totals for expected / valid / missing / invalid, cell-status counts, overall completeness. Rows where `N` is undefined are excluded from the completeness denominator and reported separately.

---

## 6. Module layout

```
C:\excel automation\
│
├── app/
│   ├── config.py               KEEP    config loading                     ✅ built
│   ├── logging_utils.py        KEEP    redaction-safe logging             ✅ built
│   ├── excel_reader.py         KEEP    workbook → CellRecord[]            ✅ built
│   ├── models.py               REWRITE slot-aware domain model
│   ├── template_spec.py        NEW     the §1.3 column map, declarative
│   ├── slot_parser.py          NEW     replaces value_splitter
│   ├── validators.py           REWRITE per-column validators + ENUM/DATE_RANGE
│   ├── row_matcher.py          NEW     replaces field_matcher (S.No/Plaza Name keyed)
│   ├── response_parser.py      REWRITE slot-aware
│   ├── consistency_checker.py  NEW     row-level cross-column checks
│   ├── qc_engine.py            REWRITE cell + row + sheet levels
│   └── report_generator.py     REWRITE new sheet layout
│
├── config/default.yaml
├── template/Format.xlsx        the fixed template (committed)
├── tests/
├── sample_data/                generated response variants (git-ignored)
├── output/
├── main.py                     CLI
└── requirements.txt
```

**Deleted** (obsoleted by having a fixed template):
- `field_type_detector.py` — types now come from `template_spec.py`
- `expected_count_detector.py` — N now comes from scaffold slots + the column-H anchor
- `value_splitter.py` / `field_matcher.py` — superseded by `slot_parser.py` / `row_matcher.py`
- `template_analyzer.py` — never written; `template_spec.py` replaces the idea entirely

Their logic is not lost: the digit-guard comma rule, enumeration stripping, and the phone/amount/date validators all carry forward into the new modules. Recoverable from git commit `03c789c` if ever needed.

---

## 7. Build phases

Each phase has a **Done when** gate. Do not start a phase until the previous gate passes.

### Phase A — `template_spec.py` (foundation)

Declarative description of §1.3, plus the constants everything else reads:

```python
SHEET_NAME       = "Data Sheet for UP STF"
HEADER_ROW       = 2
FIRST_DATA_ROW   = 3
LAST_DATA_ROW    = 117
SCAFFOLD_SLOTS   = 6            # soft cap
ANCHOR_COLUMN    = "H"
CONTRACT_WINDOW  = (date(2021,1,1), date(2026,1,14))

@dataclass(frozen=True)
class ColumnSpec:
    letter: str
    header: str                 # verbatim from the template, for verification
    role: Role                  # KEY | INPUT
    value_type: ValueType
    slotted: bool
    required: bool
    placeholders: tuple[str,...]   # e.g. ("Agency",) for H
    enum_values: tuple[str,...]    # for G, I

COLUMNS: dict[str, ColumnSpec] = { ... 19 entries ... }
```

**Done when:** a test loads `template/Format.xlsx` and asserts every `ColumnSpec.header` matches the real header text in row 2 exactly, and that `LAST_DATA_ROW`/row count match. This test is the tripwire that fires if the template is ever silently changed.

### Phase B — `models.py` rewrite

`SlotValue(slot, raw, verdict)` · `CellResult` (with `slot_values`, `missing_slots`) · `RowResult` (with `n_contracts`, `per_column`, `consistency_findings`) · `SheetSummary` · `QCRun`. Statuses and `ValueVerdict` carry over unchanged.

**Done when:** imports clean; every `ValueType` has a validator registered.

### Phase C — `slot_parser.py`

The §4 algorithm. **The highest-risk module — write its tests first**, using the exact scaffold strings from §1.4 as fixtures.

**Done when:** every row of §4's table passes, and the verbatim template scaffold for each of `H..R` is classified as *unfilled*, not as 6 values.

### Phase D — `validators.py` rewrite

The §3 table. Adds `ENUM` (fuzzy-tolerant), `DATE_RANGE`, `COMPOSITE_LOCATION`; keeps PHONE/NAME/NUMBER/ADDRESS/TEXT from v1.

**Done when:** ≥2 valid and ≥2 invalid cases per type; no validator raises on any input; no `reason` string echoes a client value.

### Phase E — `row_matcher.py`

Match template rows to response rows by S.No, then Plaza Name, then row position. Detect inserted/deleted/re-ordered rows. Verify identity columns `A..E` and report mismatches.

**Done when:** identical workbook → 115/115 matched by S.No; a workbook with 2 rows inserted at the top still matches 115/115; an edited Plaza Name is reported as an identity mismatch.

### Phase F — `response_parser.py` + `consistency_checker.py`

Parser: per cell, produce `{slot → SlotValue}` with verdicts. Checker: per row, compute `N` from H, then for every slotted column list the missing slot numbers; run the J chain-continuity and window-coverage checks; flag duplicate phones.

**Done when:** the §2.4 worked example reproduces exactly — 4 agencies, phones at slots 1–2 → `missing_slots == [3, 4]`.

### Phase G — `qc_engine.py`

The §5 tables at all three levels, plus aggregation.

**Done when:** every row of the §5.1 table is asserted; a fully-scaffold (untouched) workbook scores **0%**, not 100%; a fully-correct workbook scores 100%.

### Phase H — `report_generator.py`

`QC_Report.xlsx`:

1. **Summary** — run metadata + workbook totals + overall completeness
2. **Row Analysis** — one row per plaza: S.No, Plaza Name, RO, PIU, N, row status, completeness, count of problem columns
3. **Cell Analysis** — one row per (plaza × column): expected N, filled, valid, invalid, missing slot numbers, status, reason
4. **Slot Analysis** — one row per individual value: plaza, column, slot #, value, VALID/INVALID, reason
5. **Consistency Findings** — cross-column and date-chain problems, most severe first

Status colour-coding, frozen headers, autofilter, real `0.0%` number formats. Honour `security.redact_in_reports`.

**Done when:** opens in Excel with no repair prompt; all five sheets present; completeness sorts numerically.

### Phase I — `main.py` CLI

```powershell
python main.py --response "client_reply.xlsx" --output "output/QC_Report.xlsx"
```

`--template` defaults to `template/Format.xlsx` (it's fixed and committed). Other flags: `--config`, `--strict`, `--quiet`, `-v`, `--dump-json`.

Handle: file not found, `.xls`, password-protected, response is actually the blank template, wrong sheet name.

**Done when:** end-to-end run on synthetic responses; clear errors + exit code 2 on bad input, never a traceback.

### Phase J — synthetic responses + full test suite

Generate from the real template (copy it, fill it) into `sample_data/`:

| Variant | Expectation |
|---|---|
| `untouched.xlsx` | template as-is → **0%**, all MISSING |
| `perfect.xlsx` | 3 agencies × all columns consistent → 100% COMPLETE |
| `ragged.xlsx` | H=4 agencies, L=2 phones, K=3 names → PARTIAL, missing slots reported per column |
| `messy_format.xlsx` | commas instead of newlines, `1)` style, extra spaces, NBSP → parses identically to `perfect` |
| `unnumbered.xlsx` | values with no numbering at all → positional fallback |
| `overflow.xlsx` | 8 agencies (beyond the 6 scaffold slots) → N=8, no truncation |
| `bad_dates.xlsx` | broken chain + out-of-window dates → REVIEW with findings |
| `bad_enums.xlsx` | `Plaza Type = "Private"`, `EQ/Regular = "Yearly"` → INVALID |
| `bad_phones.xlsx` | 5-digit and 11-digit numbers → INVALID with shape reasons |
| `identity_edited.xlsx` | a Plaza Name changed → identity mismatch REVIEW |
| `rows_inserted.xlsx` | 2 rows added at top → still 115/115 matched |
| `na_marked.xlsx` | `N/A` in several cells → NOT_APPLICABLE |

**Done when:** all variants assert exact numbers (N, filled, valid, invalid, missing slots) — not just statuses. Coverage of `app/` ≥ 85%.

### Phase K — hardening

Performance on 115 rows × 19 columns (trivial, but measure). Unicode names. 30k-character cells. Corrupt files. Determinism. **Security audit:** no `requests`/`httpx`/`urllib` imported anywhere in `app/` (assert in a test); no cell values in logs; no writes outside `--output`. Write `README.md`.

---

## 8. Build order

```
A  template_spec        ← foundation, everything reads it
B  models
C  slot_parser          ← highest risk; tests first
D  validators
E  row_matcher
F  response_parser + consistency_checker
G  qc_engine
H  report_generator
I  main.py CLI
J  synthetic responses + full suite
K  hardening            ◄── MILESTONE 1
```

Phases C and D are pure string-in/verdict-out — build and test them with no Excel involved.

**After Milestone 1**, and only then: FastAPI wrapper, React dashboard (zero business logic in the frontend), Docker. A local semantic model remains **out of scope** — with a fixed template and a declarative column map there is nothing left for it to disambiguate.

---

## 9. Progress tracker

**Carried over from v1 (still valid)**
- [x] venv, requirements, .gitignore, directory skeleton
- [x] `config.py` + `config/default.yaml`
- [x] `logging_utils.py` (redaction-safe)
- [x] `excel_reader.py` (+10 tests)

**v2 build**
- [x] Phase A — `template_spec.py` + header-verification tripwire test
- [x] Phase B — `models.py` rewrite
- [x] Phase C — `slot_parser.py` + tests
- [x] Phase D — `validators.py` rewrite + tests
- [x] Phase E — `row_matcher.py` + tests
- [ ] Phase F — `response_parser.py` + `consistency_checker.py` + tests
- [ ] Phase G — `qc_engine.py` + tests
- [ ] Phase H — `report_generator.py` + tests
- [ ] Phase I — `main.py` CLI
- [ ] Phase J — synthetic responses + full suite
- [ ] Phase K — hardening + README
- [ ] **MILESTONE 1**

**Later**
- [ ] FastAPI · [ ] React dashboard · [ ] Docker

---

## 10. Open questions

Answer before the phase that depends on each. Don't guess.

1. **Phase F — "add details below the provided fields" (Instructions note).** Does a client with 8 agencies add slots `7.` and `8.` *inside the same cell*, or *insert a new row* for the plaza? The plan currently assumes in-cell (slots grow past 6) and `row_matcher` tolerates inserted rows, so both are survivable — but if inserted rows are the norm, row-level aggregation needs to merge them per plaza. **This is the highest-impact unknown.**
2. **Phase D — Plaza Type vocabulary.** Is `Public Funded / BOT / TOT / InvIT / MLFF` exhaustive, or are `HAM`, `EPC`, `BOT-Annuity` also valid? A wrong list turns valid answers into INVALID.
3. **Phase D — Contact number.** Strictly 10-digit Indian mobile, or should landlines with STD codes pass?
4. **Phase G — severity of a broken date chain.** REVIEW (current assumption) or INVALID? It's a real data-quality defect but not a formatting error.
5. **Phase E — blank/`-` Plaza Codes** (rows 25, 96, 104, 105). Will these be filled in the response, or stay as-is? Currently they're simply not used as keys.
6. **Phase G — is `Remarks` (S) ever required?** Currently optional and never counted as MISSING.
