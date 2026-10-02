"""Check extracted part numbers and quantities against the source text."""

from __future__ import annotations

import re

from app.schema import LineItem

PRESENT = "present"
AMBIGUOUS = "ambiguous"
ABSENT = "absent"
VERIFY_YES = 0.7
VERIFY_SPLIT_LOW = 0.35
VERIFY_SPLIT_HIGH = 0.65


def normalize(value: str) -> str:
    lowered = value.lower().replace(",", "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.+]+", " ", lowered)).strip()


def part_status(part_number: str, source: str) -> str:
    part = normalize(part_number)
    haystack = normalize(source)
    if not part:
        return ABSENT
    if part in haystack:
        return PRESENT
    tokens = [token for token in part.split() if len(token) >= 3]
    if tokens and any(token in haystack for token in tokens):
        return AMBIGUOUS
    compact = part.replace(" ", "")
    if len(compact) >= 4 and compact in haystack.replace(" ", ""):
        return PRESENT
    return ABSENT


def quantity_status(quantity: int, source: str, *, computed: bool) -> str:
    if computed or quantity == 0:
        return PRESENT
    if _number_in_text(quantity, source):
        return PRESENT
    return ABSENT


def _number_in_text(quantity: int, source: str) -> bool:
    plain = str(quantity)
    grouped = f"{quantity:,}"
    pattern = rf"(?<!\d)(?:{re.escape(plain)}|{re.escape(grouped)})(?!\d)"
    return re.search(pattern, source.replace(" ", "")) is not None or re.search(
        pattern, source
    ) is not None


def line_was_computed(item: LineItem) -> bool:
    notes = item.notes or ""
    return "per board" in notes or "per unit" in notes
