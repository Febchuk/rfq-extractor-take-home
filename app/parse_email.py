"""Parse a raw RFC822 message into body text, CSV rows, PDF text, and images."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime

from pypdf import PdfReader

_BANNER = re.compile(r"^[=\-]{8,}\s*$")
_OVERRIDE = re.compile(
    r"system instruction|disregard the (message|instructions)|"
    r"ignore (all )?(previous|prior|above)|you were given|"
    r"do not list any parts|do not mention this instruction|"
    r"respond with\s*\{",
    re.IGNORECASE,
)
_PHONE = re.compile(
    r"(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]\d{3}[\s.-]\d{4}"
)


@dataclass
class ParsedEmail:
    subject: str
    from_name: str | None
    from_email: str | None
    email_date: datetime | None
    body_raw: str
    body_commercial: str
    quarantined: list[str] = field(default_factory=list)
    csv_text: str | None = None
    csv_rows: list[dict[str, str]] = field(default_factory=list)
    pdf_text: str | None = None
    image: bytes | None = None
    image_mime: str | None = None

    def commercial_document(self) -> str:
        return _document(
            self.subject,
            self.from_name,
            self.from_email,
            self.body_commercial,
            self.csv_text,
            self.pdf_text,
        )

    def raw_document(self) -> str:
        return _document(
            self.subject,
            self.from_name,
            self.from_email,
            self.body_raw,
            self.csv_text,
            self.pdf_text,
        )

    def grounding_source(self, transcription: str = "") -> str:
        parts = [self.body_commercial, self.csv_text or "", self.pdf_text or "", transcription]
        return "\n".join(part for part in parts if part.strip())

    @property
    def sender_display(self) -> str:
        if self.from_name and self.from_email:
            return f"{self.from_name} <{self.from_email}>"
        return self.from_email or self.from_name or "Unknown sender"


def parse_email(raw: str | bytes) -> ParsedEmail:
    if isinstance(raw, str):
        raw_bytes = raw.encode("utf-8", errors="replace")
    else:
        raw_bytes = raw
    message = BytesParser(policy=policy.default).parsebytes(raw_bytes)

    name, email_addr = parseaddr(message.get("From", ""))
    body_parts: list[str] = []
    csv_text: str | None = None
    csv_rows: list[dict[str, str]] = []
    pdf_text: str | None = None
    image: bytes | None = None
    image_mime: str | None = None

    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        content_type = part.get_content_type()
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""

        if content_type == "text/plain" and not filename:
            body_parts.append(_decode_text(part, payload))
            continue
        if content_type in {"text/csv", "application/csv"} or (
            filename and filename.lower().endswith(".csv")
        ):
            csv_text = _decode_text(part, payload)
            csv_rows = _parse_csv(csv_text)
            continue
        if content_type == "application/pdf" or (
            filename and filename.lower().endswith(".pdf")
        ):
            pdf_text = _pdf_text(payload)
            continue
        if content_type.startswith("image/") or (
            filename and filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
        ):
            image = payload
            image_mime = content_type if content_type.startswith("image/") else "image/png"

    body_raw = "\n".join(part.strip("\n") for part in body_parts if part.strip())
    body_commercial, quarantined = quarantine_text(body_raw)
    email_date = _email_date(message.get("Date"))

    return ParsedEmail(
        subject=(message.get("Subject") or "").strip(),
        from_name=name.strip() or None,
        from_email=email_addr.strip() or None,
        email_date=email_date,
        body_raw=body_raw,
        body_commercial=body_commercial,
        quarantined=quarantined,
        csv_text=csv_text,
        csv_rows=csv_rows,
        pdf_text=pdf_text,
        image=image,
        image_mime=image_mime,
    )


def quarantine_text(text: str) -> tuple[str, list[str]]:
    """Drop obvious instruction-override blocks. The commercial text stays."""
    lines = text.splitlines()
    kept: list[str] = []
    removed: list[str] = []
    index = 0
    while index < len(lines):
        if _BANNER.match(lines[index].strip()):
            end = index + 1
            while end < len(lines) and not _BANNER.match(lines[end].strip()):
                end += 1
            if end < len(lines):
                block = lines[index : end + 1]
                block_text = "\n".join(block)
                if _OVERRIDE.search(block_text):
                    removed.append(block_text)
                    index = end + 1
                    continue
        if _OVERRIDE.search(lines[index]):
            removed.append(lines[index])
            index += 1
            continue
        kept.append(lines[index])
        index += 1
    commercial = "\n".join(kept).strip()
    return commercial, removed


def find_phone(text: str) -> str | None:
    match = _PHONE.search(text)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(0)).strip()


def guess_company(body: str, name: str | None, email_addr: str | None) -> str | None:
    """Company is usually the signature line between the person's name and email."""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    email_l = (email_addr or "").lower()
    name_l = (name or "").lower()
    closings = {"thanks", "thanks,", "regards", "regards,", "sincerely", "sincerely,", "hi,", "hello,"}
    for index, line in enumerate(lines):
        if not email_l or email_l not in line.lower():
            continue
        for prev in reversed(lines[max(0, index - 3) : index]):
            lowered = prev.lower().rstrip(",")
            if lowered == name_l or lowered in closings or "@" in prev:
                continue
            if len(prev) > 80:
                continue
            return prev.rstrip(",")
    return None


def _document(
    subject: str,
    name: str | None,
    email_addr: str | None,
    body: str,
    csv_text: str | None,
    pdf_text: str | None,
) -> str:
    header = [
        f"Subject: {subject}",
        f"From: {name or ''} <{email_addr or ''}>".strip(),
        "",
        body.strip(),
    ]
    chunks = ["\n".join(header).strip()]
    if csv_text and csv_text.strip():
        chunks.append("CSV attachment:\n" + csv_text.strip())
    if pdf_text and pdf_text.strip():
        chunks.append("PDF attachment:\n" + pdf_text.strip())
    return "\n\n".join(chunks)


def _decode_text(part, payload: bytes) -> str:
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _parse_csv(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, str]] = []
    for row in reader:
        cleaned = {
            (key or "").strip(): (value or "").strip()
            for key, value in row.items()
            if key is not None
        }
        if any(cleaned.values()):
            rows.append(cleaned)
    return rows


def _pdf_text(payload: bytes) -> str:
    reader = PdfReader(io.BytesIO(payload))
    return "\n".join((page.extract_text() or "") for page in reader.pages).strip()


def _email_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
