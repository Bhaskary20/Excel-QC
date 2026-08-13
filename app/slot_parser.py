"""One response cell's text -> {slot number: raw value}, per BUILD_PLAN.md
v2 Section 4. The highest-risk module in the project: an untouched
scaffold cell must parse as *zero* values, not six, or a blank submission
scores 100%.

Algorithm, in order:
  1. Normalize (NBSP, zero-width chars, line endings, outer whitespace).
  2. Whole-cell N/A check -> is_na, but ONLY for a non-required column (S,
     the only one). A required column has no legitimate "doesn't apply"
     case -- every operating toll plaza has real agencies, a manager, a
     consultant -- so whole-cell "N/A"/"Not Available" text there is
     treated as unfilled (-> MISSING) instead of given a free
     NOT_APPLICABLE pass. Confirmed against real client data: a plaza can
     write literal "NA" across N/O/P (Supervision Consultant, Team
     Leader, HTMS/Toll Expert) while other columns show it clearly has
     real agencies under contract -- the human reviewer flags that as a
     problem, not a deliberate opt-out.
  3. Fast-path scaffold check: text is byte-identical to the column's
     scaffold_raw (from template_spec) -> is_unfilled_scaffold, no further
     parsing needed.
  4. Numbered parse: markers like "1." "1)" "(1)" "1 . ", found anywhere a
     digit is preceded by string/line start or a space/comma/semicolon (not
     just line start -- "1. A, 2. B" on one line must still split).
  5. If fewer than 2 markers found, positional fallback: split on newline,
     then ;, then type-permitted , or / (comma uses the same digit-guard as
     v1 -- a comma between two digits is a thousands separator).
  6. Per-slot cleanup: strip quotes/trailing punctuation, drop pure
     punctuation, drop any slot whose cleaned value still equals the
     column's own placeholder text for that slot (the slow-path scaffold
     check, for cells that are *mostly* untouched), and drop any slot whose
     cleaned value is itself an NA-equivalent phrase ("N/A", "Not Assigned",
     ...). A per-slot non-answer is treated the same as a genuinely empty
     slot -- it counts toward missing_slots (MISSING/PARTIAL), not as a
     validly-answered value. This is deliberately different from a *whole
     cell* reading e.g. "N/A" (see is_na below), which is trusted at face
     value as "this column doesn't apply to this plaza."
  7. Cap at MAX_SLOTS; note if truncated.

Placeholder comparison (step 6) parses the column's scaffold_raw through
this same numbered-parse logic rather than using a hand-extracted
"placeholder string" -- so both sides of the comparison come from one
algorithm instead of two copies that could drift apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from app.config import Config
from app.template_spec import ColumnSpec, ValueType, get_column

MAX_SLOTS = 50

_NBSP = "\u00a0"
_ZERO_WIDTH_PATTERN = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_MULTI_BLANK_LINES = re.compile(r"\n{3,}")

# Matches a slot marker either at the start of the string/line, or
# immediately after whitespace/comma/semicolon/a quote mark -- so "1. A,
# 2. B" on one physical line still finds marker 2 even though
# re.MULTILINE's ^ alone would only anchor at true line starts, and a
# numbered entry wrapped in literal quotes ('"1. Ranchor Infra..."', a
# paste artifact -- found via real client data, Bhojpuri/MUDHIPAR) isn't
# invisible to the marker just because a stray quote sits in front of it.
#
# This pattern alone can't tell a real marker from an embedded number of
# the same shape -- "91.65", "46-738", "30.01.2023", "Plot No. - 83. Azad
# Colony" all look exactly like "<digit(s)><delimiter><content>" whether
# or not there's a space before the content, and whether or not what
# follows also happens to look date-shaped ("...5.24.05.2025 to
# 24.05.2026", BHARBHID -- a perfectly real final marker whose own
# content, being a date, "looks like" it's continuing a date). That
# distinction isn't made here at all -- it needs to know where the match
# sits relative to the surrounding line breaks and the numbers already
# claimed, which only _filter_implausible_jumps below has visibility into.
_SLOT_MARKER_PATTERN = re.compile(
    r"""(?:^|(?<=[\s,;"']))"""
    r"(?:\((\d{1,2})\)\s*"
    r"|(\d{1,2})\s*[.\)\-:]\s*)",
    re.MULTILINE,
)

# A marker that's missing its delimiter entirely -- just "<digit> <content>"
# with no "." ")" "-" ":" at all (e.g. "1 M/s Agency" or, mid-text, "5 Name").
# Deliberately narrower than _SLOT_MARKER_PATTERN: no delimiter to anchor on,
# so it's only trusted as a recovery mechanism for specific, constrained
# gaps (see _numbered_parse / _recover_embedded_orphans), never as a
# primary marker source.
_ORPHANED_LEADING_DIGIT = re.compile(r"^(\d{1,2})\s+(?=\S)")
_ORPHANED_EMBEDDED_MARKER = re.compile(r"\n\s*(\d{1,2})\s+(?=\S)")

# A marker that HAS its own delimiter ("2.Reguler") but sits right after a
# stray punctuation character instead of whitespace/comma/semicolon/string
# start, so _SLOT_MARKER_PATTERN's lookbehind doesn't recognize it (e.g.
# "...Reguler .2.Reguler", a stray "." glued in front of a legitimate "2."
# marker -- found via real client data, THIRPALIBADI column I). Comma and
# semicolon are excluded since those already anchor a primary match.
# Recovery still relies on the same strict host_slot < candidate <
# next_claimed bounds as the other orphan patterns for safety, since a
# short digit-plus-delimiter shape alone (e.g. inside a decimal number)
# isn't rare enough to trust on its own.
_ORPHANED_STRAY_CHAR_MARKER = re.compile(r"[^\s\w,;](\d{1,2})[.\)\-:]\s*(?=\S)")


def _find_next_orphan_match(text: str) -> Optional[re.Match]:
    matches = [m for m in (_ORPHANED_EMBEDDED_MARKER.search(text), _ORPHANED_STRAY_CHAR_MARKER.search(text)) if m]
    return min(matches, key=lambda m: m.start()) if matches else None

_SEPARATOR_PRECEDENCE = ["\n", ";", ",", "/"]
_ALLOWED_SEPARATORS: dict[ValueType, frozenset[str]] = {
    ValueType.PHONE: frozenset({"\n", ";", ",", "/"}),
    ValueType.NAME: frozenset({"\n", ";", ","}),
    ValueType.TEXT: frozenset({"\n", ";"}),
    ValueType.ADDRESS: frozenset({"\n", ";"}),  # commas are structural to an address
    ValueType.NUMBER: frozenset({"\n", ";", ","}),
    ValueType.INTEGER: frozenset({"\n", ";", ","}),
    ValueType.ENUM: frozenset({"\n", ";", ","}),
    ValueType.DATE_RANGE: frozenset({"\n", ";"}),  # "/" and internal "," belong to the date itself
    ValueType.COMPOSITE_LOCATION: frozenset({"\n", ";"}),  # commas are structural (village, city, ...)
}

# Column H is typed TEXT for validation (any non-empty string), but
# functionally it's a list of company names, not prose -- unlike N/P
# (consultant name+address, HTMS/Toll Expert), which read more like
# free text where a comma is more likely structural. Override by column
# letter rather than loosening TEXT globally.
_COLUMN_SEPARATOR_OVERRIDES: dict[str, frozenset[str]] = {
    "H": frozenset({"\n", ";", ","}),
}


def _allowed_separators_for(spec: ColumnSpec) -> frozenset[str]:
    override = _COLUMN_SEPARATOR_OVERRIDES.get(spec.letter)
    if override is not None:
        return override
    return _ALLOWED_SEPARATORS.get(spec.value_type, frozenset({"\n", ";"}))


_DIGIT_INTERNAL_COMMA_SPLIT = re.compile(r"(?<!\d),|,(?!\d)")
# Backtick included alongside the straight quotes -- same category of stray
# edge character (a typo/paste artifact, never legitimate data in any of
# the 9 value types), found via real client data: a numbered-list marker
# with no space before the content ("3.`Himanshu") left a leading backtick
# stuck to an otherwise-valid name, failing NAME validation outright instead
# of being stripped like a stray quote already is.
_LEADING_QUOTES = re.compile(r"""^['"`]+""")
_TRAILING_QUOTES = re.compile(r"""['"`]+$""")
_TRAILING_SEPARATOR_CHARS = re.compile(r"[,;.]+$")
_PURE_PUNCTUATION = re.compile(r"^\W+$")


@dataclass(frozen=True)
class SlotParseResult:
    is_na: bool
    is_unfilled_scaffold: bool
    slots: dict[int, str] = field(default_factory=dict)
    note: str = ""


def _normalize(text: Optional[str]) -> str:
    if text is None:
        return ""
    text = text.replace(_NBSP, " ")
    text = _ZERO_WIDTH_PATTERN.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _MULTI_BLANK_LINES.sub("\n\n", text)
    return text.strip()


def _is_na_token(text: str, cfg: Config) -> bool:
    na_tokens = {t.lower() for t in cfg.status.na_tokens}
    return text.strip().lower() in na_tokens


def _clean_slot_value(raw: str) -> str:
    text = raw.strip()
    text = _LEADING_QUOTES.sub("", text)
    text = _TRAILING_QUOTES.sub("", text)
    text = text.strip()
    text = _TRAILING_SEPARATOR_CHARS.sub("", text)
    return text.strip()


# A primary match here is only the markers _SLOT_MARKER_PATTERN itself
# recognizes -- one with a dropped delimiter ("5 Name" instead of "5.
# Name") or a stray character glued in front ("...Reguler .2.Reguler")
# never reaches this list at all; those are recovered separately, later,
# by _recover_embedded_orphans. So a gap between two primary matches isn't
# automatically suspicious -- "4." followed by "6." is exactly what a
# dropped "5." looks like from here, and real client data has even had two
# such drops back to back (LIMDI: primary matches land on 4 and 7, a gap
# of 3, with 5 and 6 both recovered afterward). That gap-based tolerance
# is only safe, though, for a marker that starts a genuinely fresh item --
# a real PIU always starts each new list item on its own line (or, on
# rare occasions, right after a comma/semicolon on the same line: "1. A,
# 2. B"). See _classify_match_position.
#
# Two narrower cases get a smaller benefit of the doubt -- an exact
# next-integer continuation only, never a duplicate and never a bigger
# skip, since neither position is as unambiguous as a genuinely fresh
# item:
#   - Right after "&": real client data uses it as a deliberate "and"
#     joiner for a same-line extra item ("...to 02.12.2025 (07:59:59
#     Hrs.) & 7. 02.12.2025...", KALYANPUR/KATOGHAN columns J/L/Q/R) --
#     but the *same* column also uses "&" to join an extra sub-range onto
#     an already-numbered slot with no marker of its own ("22.03.2022...
#     & 02.08.2022...", still inside slot 2), so an "&"-joined number is
#     only trusted when it's exactly the next integer in the count, not
#     whenever it merely fits somewhere.
#   - Right after a single ordinary space with a letter immediately
#     following the marker: real client data has two people joined on one
#     line with nothing but a plain space between them ("5. M/s Vikas
#     Hooda 6.M/s iiskam", NIMBIJODHA column H), exactly as legitimate as
#     the comma-joined case just missing the comma. What tells that apart
#     from an embedded number in the same position (BHARBHID: "1.
#     03.03.2022...", the day-of-month glued onto the marker) is what
#     comes right after the delimiter: real content starts with a letter,
#     an embedded number is followed by more digits ("03" continuing into
#     ".2022", "9-229" continuing into "229").
# Neither exception applies to the very first match in the whole cell
# (FULARA: an un-numbered free-text block's embedded dates
# "25.08.2025"/"26.08.2025" happened to look like a perfectly sequential
# 25-then-26 with nothing to weigh them against yet).
_MAX_FRESH_ITEM_GAP = 5


def _classify_match_position(text: str, pos: int, end: int) -> str:
    """Returns "fresh" (generous gap+duplicate tolerance), "sequential"
    (only an exact next-integer continuation, see the module comment
    above), or "suspect" (never trusted)."""
    i = pos - 1
    space_run = 0
    while i >= 0 and text[i] in " \t":
        space_run += 1
        i -= 1
    # 2+ consecutive spaces reads the same as a line break -- real client
    # data pads a dropped-delimiter marker out with a wide run of spaces
    # instead of a newline (LIMDI: "...6   Narendra" then 16 spaces before
    # a legitimate "7."), which is nothing like the single ordinary space
    # that precedes an embedded number.
    if space_run >= 2:
        return "fresh"
    if i < 0 or text[i] in "\n,;\"'":
        # A quote counts as fresh too -- a numbered entry wrapped in
        # literal quotes ('"1. Ranchor Infra..."', Bhojpuri/MUDHIPAR)
        # starts just as fresh an item as a newline would.
        return "fresh"
    if text[i] == "&":
        return "sequential"
    if end < len(text) and text[end].isalpha():
        return "sequential"
    return "suspect"


def _filter_implausible_jumps(text: str, matches: list["re.Match[str]"]) -> list["re.Match[str]"]:
    """_SLOT_MARKER_PATTERN can't itself tell a real marker from an embedded
    number of the same shape -- a decimal fraction, a house/plot number, a
    dotted date, all match just as confidently as a genuine "3." or "4."
    would (real client data: SEHATGANJ's dates, DAULATPURA/MASHORA's
    traffic figures, SURJAPUR/PANDILLAPALLI/MORATANDI's addresses, FULARA's
    free text, Manesar/Kherki Daula's dates, KALYANPUR/KATOGHAN's
    ampersand-joined ranges). See the module comments above
    _MAX_FRESH_ITEM_GAP and on _classify_match_position for what each of
    the three position classes is trusted to do. Drop any match that
    fails its class's check; its text just stays part of whichever slot
    is still open, as if it had never matched at all.
    """
    filtered = []
    running_max: Optional[int] = None
    for m in matches:
        num = int(m.group(1) or m.group(2))
        position = _classify_match_position(text, m.start(), m.end())
        if position == "suspect":
            continue
        if position == "sequential":
            if running_max is None or num != running_max + 1:
                continue
        elif running_max is not None and (num < running_max or num > running_max + _MAX_FRESH_ITEM_GAP):
            continue
        running_max = num if running_max is None else max(running_max, num)
        filtered.append(m)
    return filtered


def _numbered_parse(text: str, cfg: Optional[Config] = None) -> dict[int, str]:
    matches = _filter_implausible_jumps(text, list(_SLOT_MARKER_PATTERN.finditer(text)))

    if len(matches) < 2:
        # A lone "1." is still trustworthy -- "only one value, but numbered
        # anyway" is the common case for a single-contract row. A lone
        # marker for any OTHER number is too easily confused with ordinary
        # text ("3-BHK apartment") to trust without a second marker to
        # corroborate it.
        if len(matches) == 1:
            m = matches[0]
            if int(m.group(1) or m.group(2)) == 1:
                content = text[m.end():].strip()
                return {1: content} if content else {}
        return {}

    slots: dict[int, str] = {}

    # Leading text before the first recognized marker is often item 1 with
    # its delimiter accidentally dropped ("1 Agency Name" instead of "1.
    # Agency Name") -- real client data does this. Recover it as slot 1 if
    # that slot isn't already claimed by a proper marker.
    first_slot_num = int(matches[0].group(1) or matches[0].group(2))
    leading_text = text[: matches[0].start()].strip()
    if leading_text and first_slot_num != 1:
        orphan = _ORPHANED_LEADING_DIGIT.match(leading_text)
        if orphan:
            content = leading_text[orphan.end():].strip()
            if content:
                slots[1] = content

    for i, m in enumerate(matches):
        slot_num = int(m.group(1) or m.group(2))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = text[start:end]

        if slot_num in slots:
            # Duplicate marker (a human typo -- e.g. two entries both
            # numbered "6."). Losing data is worse than a slightly-off
            # slot number, so renumber the later one instead of discarding it.
            slot_num = max(slots.keys()) + 1
        slots[slot_num] = value

    return _recover_embedded_orphans(slots, cfg)


def _recover_embedded_orphans(slots: dict[int, str], cfg: Optional[Config] = None) -> dict[int, str]:
    """A marker that never got recognized primarily -- either its delimiter
    is missing entirely ("5 Name" instead of "5. Name") or it has a
    delimiter but sits right after stray punctuation instead of whitespace
    ("...Reguler .2.Reguler") -- gets swallowed whole into the *previous*
    recognized slot's text. Split it back out when either shape appears
    inside a slot's own text AND the digit plausibly fills the gap strictly
    between this slot and whatever's claimed next.

    Two (or more) dropped delimiters can appear back to back ("...4. Vikram
    . \\n 5 Vikram \\n 6 Narendra7. Yogesh...", real client data) -- slot 4's
    span swallows *both* orphans, so recovery has to keep re-scanning its
    own leftover tail rather than stopping after the first hit, or the
    second name stays glued onto the first (failing validation) and the
    slot it belongs in is never created at all.

    Normally requires a next-claimed slot to bound against: without an upper
    bound, the *last* slot's text has no natural ceiling, and a multi-line
    address ending in something like "...\\n5 Main Street" could misfire with
    nothing to constrain it. The one exception is when the recovered tail is
    itself a recognized non-answer phrase ("...\\n8 Not Assigned") -- real
    prose/address text never happens to end that way, so it's safe to trust
    even without a next marker to bound against. Otherwise a dropped
    delimiter on the true final item stays an unrecoverable gap, to avoid
    silently corrupting address-like free text.
    """
    if not slots:
        return slots

    claimed = sorted(slots.keys())
    result = dict(slots)

    for idx, host_slot in enumerate(claimed):
        next_claimed = claimed[idx + 1] if idx + 1 < len(claimed) else None
        current_slot = host_slot

        while True:
            match = _find_next_orphan_match(result[current_slot])
            if not match:
                break

            candidate = int(match.group(1))
            recovered = result[current_slot][match.end():].strip()

            if next_claimed is not None:
                if not (current_slot < candidate < next_claimed):
                    break
            else:
                if candidate <= current_slot or cfg is None or not _is_na_token(recovered, cfg):
                    break

            if not recovered:
                break

            result[current_slot] = result[current_slot][: match.start()].strip()
            result[candidate] = recovered
            current_slot = candidate

    return result


def _split_on(text: str, sep: str) -> list[str]:
    if sep == ",":
        return _DIGIT_INTERNAL_COMMA_SPLIT.split(text)
    return text.split(sep)


def _positional_fallback(text: str, spec: ColumnSpec) -> dict[int, str]:
    allowed = _allowed_separators_for(spec)

    for sep in _SEPARATOR_PRECEDENCE:
        if sep not in allowed:
            continue
        parts = _split_on(text, sep)
        cleaned = [p.strip() for p in parts if p.strip()]
        if len(cleaned) >= 2:
            return {i: v for i, v in enumerate(cleaned, start=1)}

    stripped = text.strip()
    return {1: stripped} if stripped else {}


@lru_cache(maxsize=None)
def _placeholder_slots_for_column(column_letter: str) -> dict[int, str]:
    spec = get_column(column_letter)
    if spec.scaffold_raw is None:
        return {}
    return {slot: _clean_slot_value(raw) for slot, raw in _numbered_parse(spec.scaffold_raw).items()}


def _parse_slotted_cell(normalized: str, spec: ColumnSpec, cfg: Config) -> SlotParseResult:
    if spec.scaffold_raw is not None and normalized == spec.scaffold_raw.strip():
        return SlotParseResult(is_na=False, is_unfilled_scaffold=True)

    raw_slots = _numbered_parse(normalized, cfg)
    if not raw_slots:
        raw_slots = _positional_fallback(normalized, spec)

    cleaned_slots: dict[int, str] = {}
    for slot_num, raw_value in raw_slots.items():
        if slot_num > MAX_SLOTS:
            continue
        cleaned = _clean_slot_value(raw_value)
        if not cleaned or _PURE_PUNCTUATION.match(cleaned) or _is_na_token(cleaned, cfg):
            continue
        cleaned_slots[slot_num] = cleaned

    placeholders = _placeholder_slots_for_column(spec.letter)
    if placeholders:
        cleaned_slots = {
            slot: value
            for slot, value in cleaned_slots.items()
            if placeholders.get(slot) != value
        }

    note = ""
    if len(raw_slots) > MAX_SLOTS:
        note = f"truncated at {MAX_SLOTS} slots"

    if not cleaned_slots:
        return SlotParseResult(is_na=False, is_unfilled_scaffold=True, note=note)

    return SlotParseResult(is_na=False, is_unfilled_scaffold=False, slots=cleaned_slots, note=note)


def parse_slots(text: Optional[str], column_letter: str, cfg: Config) -> SlotParseResult:
    spec = get_column(column_letter)
    normalized = _normalize(text)

    if not normalized:
        return SlotParseResult(is_na=False, is_unfilled_scaffold=True)

    if _is_na_token(normalized, cfg):
        if spec.required:
            return SlotParseResult(is_na=False, is_unfilled_scaffold=True)
        return SlotParseResult(is_na=True, is_unfilled_scaffold=False)

    if not spec.slotted:
        cleaned = _clean_slot_value(normalized)
        if not cleaned or _PURE_PUNCTUATION.match(cleaned):
            return SlotParseResult(is_na=False, is_unfilled_scaffold=True)
        return SlotParseResult(is_na=False, is_unfilled_scaffold=False, slots={1: cleaned})

    return _parse_slotted_cell(normalized, spec, cfg)
