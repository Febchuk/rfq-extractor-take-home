from pathlib import Path

from fastapi.testclient import TestClient

from app.classify import Classification
from app.extract import Extraction
from app.main import app
from app.pipeline import run
from app.schema import Customer, LineItem, NotRfqContract, RequestInfo, RfqContract
from app.store import store

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


class FakeClassifier:
    def __init__(self, route="rfq", confidence=0.92, injection=0.04, priority="medium"):
        self.route = route
        self.confidence = confidence
        self.injection = injection
        self.priority = priority
        self.verify_calls = 0

    def classify(self, parsed):
        return Classification(
            route=self.route,
            route_confidence=self.confidence,
            injection_probability=self.injection,
            priority=self.priority,
            priority_confidence=0.9,
        )

    def verify_parts(self, source, parts):
        self.verify_calls += 1
        return {index: 0.4 for index, _part in parts}


class FakeExtractor:
    def __init__(self, items, company=None):
        self.items = items
        self.company = company
        self.calls: list[tuple[str, str]] = []

    def extract_text(self, document, *, model, thinking):
        self.calls.append((model, thinking))
        assert "SYSTEM INSTRUCTION" not in document
        return Extraction(
            line_items=self.items,
            company=self.company,
            generative=True,
        )

    def extract_image(self, document, image, mime, *, model, thinking):
        self.calls.append((model, thinking))
        return Extraction(
            line_items=self.items,
            transcription="LM358N 10",
            company=self.company,
            generative=True,
        )


def _sample(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


def test_non_rfq_skips_the_extractor_even_when_confidence_is_low():
    extractor = FakeExtractor([])
    outcome = run(
        _sample("not-an-rfq-02-newsletter.eml"),
        classifier=FakeClassifier(route="newsletter_or_announcement", confidence=0.42),
        extractor=extractor,
    )
    assert extractor.calls == []
    assert outcome.contract.isRfq is False
    assert "Newsletter" in outcome.contract.reason
    assert "below 0.5" in outcome.contract.reason


def test_csv_line_items_come_from_the_parser():
    extractor = FakeExtractor([])
    outcome = run(
        _sample("rfq-04-csv-attachment.eml"),
        classifier=FakeClassifier(),
        extractor=extractor,
    )
    assert extractor.calls == []
    contract = outcome.contract
    assert contract.isRfq is True
    assert [item.partNumber for item in contract.lineItems] == [
        "LM7805",
        "KBPC5010",
        "1N5819",
        "LM317T",
    ]
    assert contract.lineItems[-1].quantity == 300
    assert contract.lineItems[-1].targetPrice == 1.1
    assert contract.customer.company == "PowerTech Solutions"
    assert contract.customer.email == "david.chen@powertechsolutions.com"


def test_headers_and_signature_win_on_a_bullet_rfq():
    extractor = FakeExtractor(
        [
            LineItem(partNumber="TI LM358N", quantity=500),
            LineItem(partNumber="BC547 transistor", quantity=1000),
        ],
        company="Wrong Co",
    )
    outcome = run(
        _sample("rfq-01-bullet.eml"),
        classifier=FakeClassifier(priority="medium"),
        extractor=extractor,
    )
    contract = outcome.contract
    assert contract.customer.name == "John Smith"
    assert contract.customer.email == "john.smith@acme-electronics.com"
    assert contract.customer.company == "Acme Electronics"
    assert contract.lineItems[0].partNumber == "LM358N"
    assert contract.lineItems[0].manufacturer == "TI"
    assert contract.lineItems[1].partNumber == "BC547"


def test_injection_is_quarantined_and_does_not_flip_the_route():
    extractor = FakeExtractor(
        [LineItem(partNumber="TL072CP", quantity=400)],
    )
    outcome = run(
        _sample("rfq-07-restock.eml"),
        classifier=FakeClassifier(),
        extractor=extractor,
    )
    contract = outcome.contract
    assert contract.isRfq is True
    assert contract.lineItems[0].partNumber == "TL072CP"
    assert any("quarantined" in warning for warning in contract.warnings)
    assert extractor.calls


def test_absent_part_escalates_once_and_is_kept():
    extractor = FakeExtractor([LineItem(partNumber="NOTAREALPART9", quantity=4)])
    outcome = run(
        _sample("rfq-01-bullet.eml"),
        classifier=FakeClassifier(confidence=0.8),
        extractor=extractor,
    )
    assert [call[0] for call in extractor.calls] == [
        "gemini-3.8-flash",
        "gemini-3.1-pro-preview",
    ]
    assert outcome.contract.lineItems[0].partNumber == "NOTAREALPART9"
    assert any("does not appear" in warning for warning in outcome.contract.warnings)
    assert outcome.contract.confidence < 0.8


def test_ambiguous_part_asks_jev_and_is_not_dropped():
    classifier = FakeClassifier()
    extractor = FakeExtractor([LineItem(partNumber="USB connector", quantity=300)])
    raw = (
        "From: Sam <sam@example.com>\n"
        "Subject: RFQ\n\n"
        "Please quote the USB-C 16-pin connector, qty 300.\n"
    )
    outcome = run(raw, classifier=classifier, extractor=extractor)
    assert classifier.verify_calls == 1
    assert outcome.contract.lineItems[0].partNumber == "USB connector"
    assert any("partly supported" in warning or "split" in warning for warning in outcome.contract.warnings)


def test_inbox_shows_both_probabilities_only_when_they_disagree():
    store.clear()
    store.add(
        subject="Agreeing quote",
        sender="buyer@example.com",
        contract=RfqContract(
            confidence=0.9,
            customer=Customer(name="Ada"),
            request=RequestInfo(),
            lineItems=[LineItem(partNumber="LM358N", quantity=10)],
            warnings=[],
        ),
        quote_probability=0.91,
        has_parts_probability=0.88,
    )
    store.add(
        subject="Parts without a quote",
        sender="news@example.com",
        contract=NotRfqContract(
            confidence=0.95,
            reason="Newsletter or product announcement, not a request for quotation",
        ),
        quote_probability=0.08,
        has_parts_probability=0.91,
    )
    page = TestClient(app).get("/")
    assert "Parts list 0.91" in page.text
    assert "Quote 0.08" in page.text
    assert "Parts list 0.88" not in page.text
    assert "Quote 0.91" not in page.text
    store.clear()


def test_catalog_sidecar_leaves_the_contract_fields_alone():
    extractor = FakeExtractor(
        [
            LineItem(partNumber="LM358N", manufacturer="TI", quantity=500),
            LineItem(partNumber="10K 0805", quantity=5000),
        ]
    )
    outcome = run(
        _sample("rfq-01-bullet.eml"),
        classifier=FakeClassifier(confidence=0.9),
        extractor=extractor,
    )
    contract = outcome.contract
    assert contract.lineItems[0].partNumber == "LM358N"
    assert contract.lineItems[0].manufacturer == "TI"
    assert contract.lineItems[1].partNumber == "10K 0805"
    assert outcome.catalog_matches[0].kind == "exact"
    assert outcome.catalog_matches[1].candidates[0].mpn == "RC0805FR-0710KL"
    assert "catalog" not in contract.model_dump()


def test_missing_key_on_the_form_is_an_error_page(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store.clear()
    client = TestClient(app)
    response = client.post("/ingest", data={"raw": "From: a@b.com\nSubject: Hi\n\nHello"})
    assert response.status_code == 503
    assert "TYPESAFE_API_KEY" in response.text
    assert "Could not ingest" in response.text
    store.clear()


def test_post_ingest_returns_the_contract_and_lists_it():
    store.clear()

    def fake_run(raw):
        from app.pipeline import Outcome
        from app.schema import NotRfqContract

        return Outcome(
            contract=NotRfqContract(
                confidence=0.95,
                reason="Newsletter or product announcement, not a request for quotation",
            ),
            subject="New Product Announcement - ESP32-C6",
            sender="news@espressif-updates.com",
        )

    import app.main as main

    original = main.run
    main.run = fake_run
    try:
        client = TestClient(app)
        response = client.post(
            "/ingest",
            content=_sample("not-an-rfq-02-newsletter.eml").encode(),
            headers={"content-type": "message/rfc822"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["isRfq"] is False
        assert "reason" in body
        assert "warnings" not in body
        page = client.get("/")
        assert page.status_code == 200
        assert "New Product Announcement" in page.text
        assert "Not an RFQ" in page.text
        record_id = store.list()[0].id
        detail = client.get(f"/rfqs/{record_id}")
        assert detail.status_code == 200
        assert "Newsletter or product announcement" in detail.text
    finally:
        main.run = original
        store.clear()
