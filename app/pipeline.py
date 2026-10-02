"""Custom-logic pipeline: parse, classify, extract, verify, return the contract."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.catalog import LineCatalog, annotate
from app.classify import INJECTION_THRESHOLD, Classification, JevClient, reason_for
from app.extract import Extraction, GeminiExtractor, model_name
from app.parse_email import ParsedEmail, find_phone, guess_company, parse_email
from app.policies import ROUTE_CONFIDENCE_FLOOR, apply_confidence, apply_policies
from app.schema import Customer, LineItem, NotRfqContract, Note, RequestInfo, RfqContract
from app.verify import (
    ABSENT,
    AMBIGUOUS,
    VERIFY_SPLIT_HIGH,
    VERIFY_SPLIT_LOW,
    VERIFY_YES,
    line_was_computed,
    part_status,
    quantity_status,
)


@dataclass
class Outcome:
    contract: RfqContract | NotRfqContract
    subject: str
    sender: str
    quote_probability: float = 0.0
    has_parts_probability: float = 0.0
    catalog_matches: list[LineCatalog] = field(default_factory=list)


def run(
    raw: str | bytes,
    *,
    classifier: JevClient | None = None,
    extractor: GeminiExtractor | None = None,
) -> Outcome:
    parsed = parse_email(raw)
    classifier = classifier or JevClient()
    extractor = extractor or GeminiExtractor()
    classification = classifier.classify(parsed)
    if not classification.is_rfq:
        return Outcome(
            contract=NotRfqContract(
                confidence=round(min(1.0, max(0.0, classification.route_confidence)), 2),
                reason=reason_for(classification, quarantined=bool(parsed.quarantined)),
            ),
            subject=parsed.subject,
            sender=parsed.sender_display,
            quote_probability=classification.quote_probability,
            has_parts_probability=classification.has_parts_probability,
        )

    extraction = _extract(parsed, extractor, escalation=False)
    contract, matches = _assemble(
        parsed, classification, extraction, classifier, escalated=False, extractor=extractor
    )
    return Outcome(
        contract=contract,
        subject=parsed.subject,
        sender=parsed.sender_display,
        quote_probability=classification.quote_probability,
        has_parts_probability=classification.has_parts_probability,
        catalog_matches=matches,
    )


def _extract(parsed: ParsedEmail, extractor: GeminiExtractor, *, escalation: bool) -> Extraction:
    model = model_name(escalation)
    if parsed.image:
        thinking = "medium"
        return extractor.extract_image(
            parsed.commercial_document(),
            parsed.image,
            parsed.image_mime or "image/png",
            model=model,
            thinking=thinking,
        )
    if parsed.csv_rows and not parsed.pdf_text:
        return Extraction(
            line_items=_lines_from_csv(parsed.csv_rows),
            generative=False,
        )
    thinking = "medium" if escalation else "low"
    return extractor.extract_text(parsed.commercial_document(), model=model, thinking=thinking)


def _assemble(
    parsed: ParsedEmail,
    classification: Classification,
    extraction: Extraction,
    classifier: JevClient,
    *,
    escalated: bool,
    extractor: GeminiExtractor,
) -> tuple[RfqContract, list[LineCatalog]]:
    items, due, instructions, notes = apply_policies(
        extraction.line_items,
        parsed.grounding_source(extraction.transcription),
        email_date=parsed.email_date,
        due_date=extraction.due_date,
        special_instructions=extraction.special_instructions,
    )
    source = parsed.grounding_source(extraction.transcription)
    absent = [item.partNumber for item in items if part_status(item.partNumber, source) == ABSENT]
    if (absent or not items) and extraction.generative and not escalated:
        retry = _extract(parsed, extractor, escalation=True)
        extraction = Extraction(
            line_items=retry.line_items,
            company=retry.company or extraction.company,
            due_date=retry.due_date or extraction.due_date,
            special_instructions=retry.special_instructions or extraction.special_instructions,
            transcription=retry.transcription or extraction.transcription,
            generative=True,
        )
        return _assemble(
            parsed,
            classification,
            extraction,
            classifier,
            escalated=True,
            extractor=extractor,
        )

    notes = _ground_notes(items, source, notes)
    ambiguous = [
        (index, item.partNumber)
        for index, item in enumerate(items)
        if part_status(item.partNumber, source) == AMBIGUOUS
    ]
    if ambiguous:
        probabilities = classifier.verify_parts(source, ambiguous)
        for index, part in ambiguous:
            probability = probabilities.get(index, 0.0)
            if probability >= VERIFY_YES:
                continue
            if VERIFY_SPLIT_LOW <= probability <= VERIFY_SPLIT_HIGH:
                notes.append(
                    Note(
                        text=(
                            f"{part}: the check on whether this part was requested is split "
                            f"(p={probability:.2f}). Left in place for a person to review."
                        )
                    )
                )
            else:
                notes.append(
                    Note(
                        text=(
                            f"{part}: only partly supported by the source "
                            f"(p={probability:.2f}). Left in place for a person to review."
                        )
                    )
                )

    catalog_matches, catalog_notes = annotate(items)
    notes.extend(catalog_notes)
    header_notes = _header_notes(parsed, classification)
    all_notes = header_notes + notes
    if not items:
        all_notes.append(Note(text="No line items could be extracted."))

    company = guess_company(parsed.body_commercial, parsed.from_name, parsed.from_email)
    if not company:
        company = extraction.company

    contract = RfqContract(
        confidence=apply_confidence(classification.route_confidence, all_notes),
        customer=Customer(
            name=parsed.from_name,
            email=parsed.from_email,
            phone=find_phone(parsed.body_commercial),
            company=company,
        ),
        request=RequestInfo(
            dueDate=_clean_date(due),
            priority=classification.priority,  # type: ignore[arg-type]
            specialInstructions=instructions,
        ),
        lineItems=items,
        warnings=[note.text for note in all_notes],
    )
    return contract, catalog_matches


def _ground_notes(items: list[LineItem], source: str, notes: list[Note]) -> list[Note]:
    extra: list[Note] = []
    for item in items:
        status = part_status(item.partNumber, source)
        if status == ABSENT:
            extra.append(
                Note(
                    text=(
                        f"{item.partNumber}: part number does not appear in the source "
                        "email or attachment. Left in place for a person to review."
                    )
                )
            )
        qty = quantity_status(item.quantity, source, computed=line_was_computed(item))
        if qty == ABSENT:
            extra.append(
                Note(
                    text=(
                        f"{item.partNumber}: quantity {item.quantity} does not appear in the source. "
                        "Left in place for a person to review."
                    )
                )
            )
    return notes + extra


def _header_notes(parsed: ParsedEmail, classification: Classification) -> list[Note]:
    notes: list[Note] = []
    if parsed.quarantined:
        notes.append(
            Note(
                text=(
                    "The email contained an instruction-override block. "
                    "It was quarantined and did not change the route."
                ),
                penalize=False,
            )
        )
    elif classification.injection_probability >= INJECTION_THRESHOLD:
        notes.append(
            Note(
                text=(
                    "The email appears to contain an instruction-override attempt "
                    f"(p={classification.injection_probability:.2f}). It did not change the route."
                ),
                penalize=False,
            )
        )
    if classification.route_confidence < ROUTE_CONFIDENCE_FLOOR:
        notes.append(
            Note(
                text=(
                    f"Route confidence was {classification.route_confidence:.2f}, below 0.5. "
                    "Extraction continued."
                ),
                penalize=False,
            )
        )
    return notes


def _lines_from_csv(rows: list[dict[str, str]]) -> list[LineItem]:
    items: list[LineItem] = []
    for row in rows:
        part = row.get("Part Number") or row.get("partNumber") or ""
        if not part:
            continue
        manufacturer = row.get("Manufacturer") or None
        notes = row.get("Notes") or None
        items.append(
            LineItem(
                partNumber=part,
                manufacturer=manufacturer or None,
                description=None,
                quantity=_parse_int(row.get("Quantity")),
                targetPrice=_parse_price(row.get("Target Price")),
                notes=notes or None,
            )
        )
    return items


def _parse_int(value: str | None) -> int:
    if not value:
        return 0
    digits = value.replace(",", "").strip()
    try:
        return int(float(digits))
    except ValueError:
        return 0


def _parse_price(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _clean_date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if len(text) >= 10:
        text = text[:10]
    parts = text.split("-")
    if len(parts) != 3 or len(parts[0]) != 4:
        return None
    return text
