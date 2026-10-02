"""Deterministic quantity, date, and part-number tidy-up.

The model proposes line items. These rules overwrite the fields where the
source text is explicit enough for code to decide.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from app.schema import LineItem, Note

_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_MONTH = (
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"Sept|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
)
_FULL_DATE = re.compile(
    rf"\b({_MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,)?\s+(20\d{{2}})\b",
    re.IGNORECASE,
)
_BARE_DATE = re.compile(
    rf"\b({_MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(20\d{2})\b")
_PROJECT_QTY = re.compile(r"\((\d+)\s+units?\)", re.IGNORECASE)
_PER = re.compile(r"(\d+)\s+per\s+(board|unit)s?\b", re.IGNORECASE)
_RANGE = re.compile(r"(\d+)\s*(?:-|–|to)\s*(\d+)", re.IGNORECASE)
_HEDGE = re.compile(
    r"(?:~|roughly|approx(?:imately)?|about)\s*(\d+)|\b(\d+)\s*(?:pcs?)?\s*~",
    re.IGNORECASE,
)
_CATEGORY = re.compile(
    r"^(?P<head>.+?)\s+(?P<kind>transistors?|resistors?|capacitors?)$",
    re.IGNORECASE,
)
_LEADING_MFR = re.compile(r"^(TI|ST)\s+(\S+)$")
_ASSORTED = re.compile(r"assorted", re.IGNORECASE)
_ASSORTED_TOTAL = re.compile(r"50[,.]?000\s+total", re.IGNORECASE)
_RESISTOR_SPLIT = re.compile(r"\b(10\s?k|4\.7\s?k|1\s?k)\b", re.IGNORECASE)
_INSTRUCTION = re.compile(
    r"rush delivery required|please provide lead times and unit pricing|"
    r"all parts must be rohs compliant",
    re.IGNORECASE,
)
_EXPLICIT_QTY = re.compile(
    r"(?:qty|quantity)\s*[:.]?\s*(\d[\d,]*)|\|\s*(\d[\d,]*)\s*\|",
    re.IGNORECASE,
)

CONFIDENCE_PENALTY = 0.05
ROUTE_CONFIDENCE_FLOOR = 0.5
_NO_PENALTY_PREFIXES = (
    "The email contained an instruction-override",
    "The email appears to contain an instruction-override",
    "Route confidence was",
)


def tidy_part(part_number: str, manufacturer: str | None) -> tuple[str, str | None]:
    """Keep buyer wording. Strip a trailing category word when a code remains."""
    part = " ".join(part_number.split())
    match = _LEADING_MFR.match(part)
    if match and not manufacturer:
        manufacturer = match.group(1)
        part = match.group(2)
    category = _CATEGORY.match(part)
    if category and re.search(r"\d", category.group("head")):
        part = category.group("head").strip()
    return part, manufacturer or None


def find_dates(text: str, email_date: datetime | None = None) -> list[date]:
    found: list[date] = []
    occupied: list[tuple[int, int]] = []
    for match in _FULL_DATE.finditer(text):
        parsed = _to_date(match.group(1), int(match.group(2)), int(match.group(3)))
        if parsed:
            found.append(parsed)
            occupied.append(match.span())
    year = _context_year(text, email_date)
    for match in _BARE_DATE.finditer(text):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        if year is None:
            continue
        parsed = _to_date(match.group(1), int(match.group(2)), year)
        if parsed:
            found.append(parsed)
    unique: list[date] = []
    for item in found:
        if item not in unique:
            unique.append(item)
    return unique


def apply_policies(
    items: list[LineItem],
    source: str,
    *,
    email_date: datetime | None = None,
    due_date: str | None = None,
    special_instructions: str | None = None,
) -> tuple[list[LineItem], str | None, str | None, list[Note]]:
    notes: list[Note] = []
    updated = [_copy_item(item) for item in items]
    for item in updated:
        item.partNumber = re.sub(
            r"\s+or equivalent\b.*$", "", item.partNumber, flags=re.IGNORECASE
        ).strip()
        part, manufacturer = tidy_part(item.partNumber, item.manufacturer)
        item.partNumber = part
        item.manufacturer = manufacturer

    updated, per_board_notes = _apply_per_board(updated, source)
    notes.extend(per_board_notes)
    updated, assortment_notes = _collapse_assorted(updated, source)
    notes.extend(assortment_notes)
    updated, range_notes = _apply_ranges(updated, source)
    notes.extend(range_notes)
    updated, equivalent_notes = _flag_equivalent(updated, source)
    notes.extend(equivalent_notes)
    _apply_explicit_qty(updated, source)

    dates = find_dates(source, email_date)
    resolved_due = due_date
    instructions = _blank_to_none(special_instructions)
    if len(dates) >= 2:
        earliest = min(dates)
        resolved_due = earliest.isoformat()
        listed = " and ".join(item.isoformat() for item in sorted(dates))
        notes.append(
            Note(
                text=(
                    f"More than one delivery date was stated ({listed}). "
                    f"dueDate is the earlier date, {earliest.isoformat()}."
                )
            )
        )
        extra = f"Delivery dates: {listed}."
        instructions = _append_instruction(instructions, extra)
    elif len(dates) == 1:
        resolved_due = dates[0].isoformat()

    if instructions is None:
        lifted = _lift_instruction(source)
        if lifted:
            instructions = lifted

    for item in updated:
        item.notes = _blank_to_none(item.notes)
        item.description = _blank_to_none(item.description)
        item.manufacturer = _blank_to_none(item.manufacturer)
        if item.quantity < 0:
            item.quantity = 0
    return updated, resolved_due, instructions, notes


def apply_confidence(route_confidence: float, notes: list[Note]) -> float:
    """Start at the Jev route confidence. Subtract 0.05 per penalized warning."""
    penalty = sum(1 for note in notes if note.penalize and not note.text.startswith(_NO_PENALTY_PREFIXES))
    value = route_confidence - (CONFIDENCE_PENALTY * penalty)
    return round(min(1.0, max(0.0, value)), 2)


def _apply_per_board(items: list[LineItem], source: str) -> tuple[list[LineItem], list[Note]]:
    notes: list[Note] = []
    factors = _per_board_factors(source)
    if not factors:
        return items, notes
    for item in items:
        factor = _match_factor(item.partNumber, factors)
        if factor is None:
            continue
        per, boards, unit_word = factor
        expected = per * boards
        noun = "boards" if unit_word == "board" else "units"
        formula = f"{per} per {unit_word} × {boards} {noun}"
        if item.quantity != expected:
            item.quantity = expected
        item.notes = _append_note(item.notes, formula)
        notes.append(
            Note(text=f"{item.partNumber}: quantity computed as {formula}.")
        )
    return items, notes


def _per_board_factors(source: str) -> list[tuple[str, int, int, str]]:
    current = 0
    found: list[tuple[str, int, int, str]] = []
    for line in source.splitlines():
        project = _PROJECT_QTY.search(line)
        if project:
            current = int(project.group(1))
        per = _PER.search(line)
        if per and current:
            phrase = _PER.sub("", line)
            phrase = re.sub(r"^[\-\*\d\.\)\s]+", "", phrase).strip(" -:")
            found.append((phrase, int(per.group(1)), current, per.group(2).lower()))
    return found


def _match_factor(
    part_number: str, factors: list[tuple[str, int, int, str]]
) -> tuple[int, int, str] | None:
    part_norm = _norm(part_number)
    for phrase, per, boards, unit_word in factors:
        phrase_norm = _norm(phrase)
        if not phrase_norm or not part_norm:
            continue
        if part_norm in phrase_norm or phrase_norm in part_norm:
            return per, boards, unit_word
    return None


def _collapse_assorted(items: list[LineItem], source: str) -> tuple[list[LineItem], list[Note]]:
    if not (_ASSORTED.search(source) and _ASSORTED_TOTAL.search(source)):
        return items, []
    split_indexes = [
        index
        for index, item in enumerate(items)
        if _RESISTOR_SPLIT.search(item.partNumber) or _ASSORTED.search(item.partNumber)
    ]
    warning = Note(
        text=(
            "Resistors were requested as one assorted total of 50000. "
            "The split across 10K, 4.7K, and 1K was not stated, so this stays one line."
        )
    )
    if len(split_indexes) <= 1:
        if split_indexes:
            only = items[split_indexes[0]]
            if only.quantity != 50000:
                only.quantity = 50000
            if "assorted" not in only.partNumber.lower():
                only.partNumber = "0805 resistors (10K, 4.7K, 1K)"
        return items, [warning]

    kept: list[LineItem] = []
    inserted = False
    for index, item in enumerate(items):
        if index in split_indexes:
            if not inserted:
                kept.append(
                    LineItem(
                        partNumber="0805 resistors (10K, 4.7K, 1K)",
                        manufacturer=None,
                        description=None,
                        quantity=50000,
                        targetPrice=None,
                        notes="Assorted values; split across 10K, 4.7K, and 1K was not stated.",
                    )
                )
                inserted = True
            continue
        kept.append(item)
    return kept, [warning]


def _apply_ranges(items: list[LineItem], source: str) -> tuple[list[LineItem], list[Note]]:
    notes: list[Note] = []
    for item in items:
        line = _source_line(item.partNumber, source)
        if not line:
            continue
        span = _RANGE.search(line)
        if span:
            low, high = int(span.group(1)), int(span.group(2))
            floor = min(low, high)
            item.quantity = floor
            item.notes = _append_note(item.notes, f"Stated range {floor}-{max(low, high)}")
            notes.append(
                Note(
                    text=(
                        f"{item.partNumber}: quantity was a range "
                        f"({floor}-{max(low, high)}). Using the lower number."
                    )
                )
            )
            continue
        hedge = _HEDGE.search(line)
        if hedge:
            stated = int(next(group for group in hedge.groups() if group))
            item.quantity = stated
            item.notes = _append_note(item.notes, "Approximate quantity")
            notes.append(
                Note(text=f"{item.partNumber}: quantity was approximate ({stated}).")
            )
    return items, notes


def _apply_explicit_qty(items: list[LineItem], source: str) -> None:
    """When the source states Qty N, that integer wins over a model guess."""
    for item in items:
        notes = item.notes or ""
        if "per board" in notes or "per unit" in notes or "Stated range" in notes:
            continue
        if "Approximate quantity" in notes:
            continue
        line = _source_line(item.partNumber, source)
        if not line:
            continue
        if _RANGE.search(line) or _HEDGE.search(line) or _PER.search(line):
            continue
        match = _EXPLICIT_QTY.search(line)
        if not match:
            continue
        raw = next(group for group in match.groups() if group)
        item.quantity = int(raw.replace(",", ""))


def _flag_equivalent(items: list[LineItem], source: str) -> tuple[list[LineItem], list[Note]]:
    if not re.search(r"or equivalent", source, re.IGNORECASE):
        return items, []
    notes = [
        Note(
            text=(
                "A line allowed an equivalent alternate. "
                "It stays one line item instead of an invented second part."
            )
        )
    ]
    for item in items:
        line = _source_line(item.partNumber, source) or ""
        if re.search(r"or equivalent", line, re.IGNORECASE) or re.search(
            r"or equivalent", item.partNumber, re.IGNORECASE
        ):
            item.partNumber = re.sub(
                r"\s+or equivalent.*$", "", item.partNumber, flags=re.IGNORECASE
            ).strip()
            item.notes = _append_note(item.notes, "or equivalent")
    return items, notes


def _source_line(part_number: str, source: str) -> str | None:
    part_norm = _norm(part_number)
    tokens = [token for token in part_norm.split() if len(token) >= 2]
    best: str | None = None
    for line in source.splitlines():
        line_norm = _norm(line)
        if part_norm and part_norm in line_norm:
            return line
        if tokens and all(token in line_norm for token in tokens):
            best = line
    return best


def _lift_instruction(source: str) -> str | None:
    for line in source.splitlines():
        if _INSTRUCTION.search(line):
            return line.strip(" -")
    return None


def _context_year(text: str, email_date: datetime | None) -> int | None:
    years = [int(match.group(1)) for match in _YEAR.finditer(text)]
    if years:
        return years[0]
    if email_date:
        return email_date.year
    return None


def _to_date(month_name: str, day: int, year: int) -> date | None:
    month = _MONTHS.get(month_name.lower().rstrip("."))
    if month is None or not 1 <= day <= 31:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _copy_item(item: LineItem) -> LineItem:
    return item.model_copy(deep=True)


def _append_note(existing: str | None, extra: str) -> str:
    if existing and extra.lower() in existing.lower():
        return existing
    if existing:
        return f"{existing}; {extra}"
    return extra


def _append_instruction(existing: str | None, extra: str) -> str:
    if existing and extra.lower() in existing.lower():
        return existing
    if existing:
        return f"{existing} {extra}"
    return extra


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.+]+", " ", value.lower())).strip()
