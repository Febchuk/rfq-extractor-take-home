from pathlib import Path

from app.parse_email import parse_email, quarantine_text

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


def _read(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


def test_quarantine_removes_override_and_keeps_parts():
    parsed = parse_email(_read("rfq-07-restock.eml"))
    assert "TL072CP" in parsed.body_commercial
    assert "STM32F103C8T6" in parsed.body_commercial
    assert "SYSTEM INSTRUCTION" not in parsed.body_commercial
    assert "isRfq" not in parsed.body_commercial
    assert parsed.quarantined
    assert "SYSTEM INSTRUCTION" in parsed.body_raw


def test_quarantine_leaves_ordinary_mail_unchanged():
    text = "Please quote 500 of LM358N.\nThanks"
    commercial, removed = quarantine_text(text)
    assert commercial == text
    assert removed == []


def test_csv_attachment_rows():
    parsed = parse_email(_read("rfq-04-csv-attachment.eml"))
    assert parsed.from_name == "David Chen"
    assert parsed.from_email == "david.chen@powertechsolutions.com"
    parts = [row["Part Number"] for row in parsed.csv_rows]
    assert parts == ["LM7805", "KBPC5010", "1N5819", "LM317T"]
    lm317 = parsed.csv_rows[-1]
    assert lm317["Quantity"] == "300"
    assert lm317["Target Price"] == "1.10"
    assert lm317["Notes"] == "Adjustable regulator"
    assert lm317["Manufacturer"] == ""


def test_pdf_text_and_body_only_part():
    parsed = parse_email(_read("rfq-05-pdf-attachment.eml"))
    assert "STM32F407VGT6" in (parsed.pdf_text or "")
    assert "USB-C 16-pin connector" in (parsed.pdf_text or "")
    assert "NEO-6M" in parsed.body_commercial
    assert "NEO-6M" not in (parsed.pdf_text or "")
    assert parsed.from_email == "s.lin@northwindcontrols.com"


def test_image_attachment_is_kept():
    parsed = parse_email(_read("rfq-08-image.eml"))
    assert parsed.image
    assert parsed.image_mime == "image/png"
    assert parsed.csv_rows == []
