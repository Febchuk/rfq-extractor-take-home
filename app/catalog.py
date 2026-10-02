"""Catalog suggestions beside the contract. Part numbers are not rewritten."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.schema import LineItem, Note

_ROOT = Path(__file__).resolve().parents[1]
_CATALOG = _ROOT / "samples" / "parts-catalog.csv"

_ALIASES = {
    "TI": "Texas Instruments",
    "ON SEMI": "ON Semiconductor",
    "ST": "STMicroelectronics",
}

_TOKEN = re.compile(r"[A-Z0-9]+")
_STOP = {
    "AND",
    "CAPACITOR",
    "DIODE",
    "DUAL",
    "FOR",
    "OR",
    "PRECISION",
    "RESISTOR",
    "THE",
    "TRANSISTOR",
    "WITH",
}


@dataclass(frozen=True)
class CatalogRow:
    mpn: str
    manufacturer: str
    description: str


@dataclass
class LineCatalog:
    kind: str
    chosen: CatalogRow | None
    candidates: list[CatalogRow]
    manufacturer_alias: str | None
    warning: str | None

    @property
    def summary(self) -> str:
        alias = self.manufacturer_alias or ""
        if self.kind == "exact" and self.chosen:
            text = (
                f"Catalog: {self.chosen.mpn} · {self.chosen.manufacturer} · "
                f"{self.chosen.description}"
            )
            return f"{text}. {alias}" if alias else text
        if self.kind == "package":
            listed = ", ".join(
                f"{row.mpn} ({row.description})" for row in self.candidates
            )
            text = f"Not chosen. Could be {listed}. The package was not guessed."
            return f"{text} {alias}" if alias else text
        if self.kind == "description" and self.candidates:
            listed = "; ".join(
                f"{row.mpn} · {row.manufacturer} · {row.description}"
                for row in self.candidates
            )
            text = f"Suggestion only: {listed}. Not copied into the part number."
            return f"{text} {alias}" if alias else text
        return alias


def annotate(items: list[LineItem]) -> tuple[list[LineCatalog], list[Note]]:
    rows = load_catalog()
    matches: list[LineCatalog] = []
    notes: list[Note] = []
    for item in items:
        match = _match_line(item, rows)
        matches.append(match)
        if match.warning:
            notes.append(Note(text=match.warning))
    return matches, notes


@lru_cache(maxsize=1)
def load_catalog() -> tuple[CatalogRow, ...]:
    rows: list[CatalogRow] = []
    with _CATALOG.open(newline="", encoding="utf-8") as handle:
        for record in csv.DictReader(handle):
            mpn = (record.get("mpn") or "").strip()
            if not mpn:
                continue
            rows.append(
                CatalogRow(
                    mpn=mpn,
                    manufacturer=(record.get("manufacturer") or "").strip(),
                    description=(record.get("description") or "").strip(),
                )
            )
    return tuple(rows)


def _match_line(item: LineItem, rows: tuple[CatalogRow, ...]) -> LineCatalog:
    alias = _alias_note(item.manufacturer)
    exact = _exact(item.partNumber, rows)
    if exact:
        return LineCatalog("exact", exact, [exact], alias, None)
    packages = _package_hits(item.partNumber, rows)
    if len(packages) >= 2:
        names = ", ".join(row.mpn for row in packages)
        warning = (
            f"{item.partNumber} matches more than one catalog package ({names}). "
            "The package was not guessed."
        )
        return LineCatalog("package", None, packages, alias, warning)
    if len(packages) == 1:
        return LineCatalog("description", None, packages, alias, None)
    described = _description_hits(item.partNumber, rows)
    if described:
        return LineCatalog("description", None, described, alias, None)
    return LineCatalog("none", None, [], alias, None)


def _exact(part: str, rows: tuple[CatalogRow, ...]) -> CatalogRow | None:
    key = _norm_mpn(part)
    if not key:
        return None
    for row in rows:
        if _norm_mpn(row.mpn) == key:
            return row
    return None


def _package_hits(part: str, rows: tuple[CatalogRow, ...]) -> list[CatalogRow]:
    stem = _alnum(part)
    if len(stem) < 4 or " " in part.strip():
        return []
    hits: list[CatalogRow] = []
    for row in rows:
        mpn = _alnum(row.mpn)
        if not mpn.startswith(stem) or len(mpn) <= len(stem):
            continue
        suffix = mpn[len(stem) :]
        if 1 <= len(suffix) <= 4 and any(character.isalpha() for character in suffix):
            hits.append(row)
    return hits


def _description_hits(part: str, rows: tuple[CatalogRow, ...]) -> list[CatalogRow]:
    wanted = _tokens(part)
    if len(wanted) < 2:
        return []
    scored: list[tuple[int, int, CatalogRow]] = []
    for index, row in enumerate(rows):
        overlap = wanted & _tokens(row.description)
        if len(overlap) >= 2:
            scored.append((len(overlap), -index, row))
    scored.sort(reverse=True)
    if not scored:
        return []
    best = scored[0][0]
    return [row for overlap, _index, row in scored if overlap == best][:5]


def _alias_note(manufacturer: str | None) -> str | None:
    if not manufacturer:
        return None
    key = " ".join(manufacturer.upper().split())
    canonical = _ALIASES.get(key)
    if not canonical:
        return None
    return f"{manufacturer.strip()} is an alias of {canonical}"


def _norm_mpn(value: str) -> str:
    return re.sub(r"[^A-Z0-9.\-]", "", value.upper())


def _alnum(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _tokens(value: str) -> set[str]:
    return {token for token in _TOKEN.findall(value.upper()) if len(token) >= 2 and token not in _STOP}
