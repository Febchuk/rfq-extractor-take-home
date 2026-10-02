from app.policies import apply_confidence, apply_policies, find_dates, tidy_part
from app.schema import LineItem, Note
from app.verify import ABSENT, AMBIGUOUS, PRESENT, part_status, quantity_status


def test_part_grounding_present_ambiguous_and_absent():
    source = "TI LM358N - Qty 500\n- 10K 0805 resistor - Qty 5000\nUSB-C 16-pin connector"
    assert part_status("LM358N", source) == PRESENT
    assert part_status("10K 0805", source) == PRESENT
    assert part_status("USB connector", source) == AMBIGUOUS
    assert part_status("NOTAREALPART9", source) == ABSENT


def test_quantity_grounding_ignores_computed_values():
    source = "Qty 500"
    assert quantity_status(500, source, computed=False) == PRESENT
    assert quantity_status(1000, source, computed=False) == ABSENT
    assert quantity_status(1000, source, computed=True) == PRESENT
    assert quantity_status(50000, "50,000 total", computed=False) == PRESENT


def test_tidy_part_strips_category_and_leading_ti():
    assert tidy_part("BC547 transistor", None) == ("BC547", None)
    assert tidy_part("10K 0805 resistor", None) == ("10K 0805", None)
    assert tidy_part("100nF 0603 capacitor", None) == ("100nF 0603", None)
    assert tidy_part("TI LM358N", None) == ("LM358N", "TI")
    assert tidy_part("Relay 5V 10A SPDT", None) == ("Relay 5V 10A SPDT", None)


def test_ranges_use_the_floor_and_hedges_keep_the_stated_number():
    source = "\n".join(
        [
            "- ATmega328P - need about 100-150 units",
            "- ESP8266 modules (roughly 200)",
            "- LM2596 buck converters - 50 to 75 pieces",
            '- 0.96" OLED displays ~100pcs',
            "- DHT22 sensors (approx. 25-30)",
        ]
    )
    items = [
        LineItem(partNumber="ATmega328P", quantity=150),
        LineItem(partNumber="ESP8266", quantity=0),
        LineItem(partNumber="LM2596", quantity=75),
        LineItem(partNumber='0.96" OLED displays', quantity=0),
        LineItem(partNumber="DHT22", quantity=30),
    ]
    updated, _due, _instructions, notes = apply_policies(items, source)
    quantities = {item.partNumber: item.quantity for item in updated}
    assert quantities["ATmega328P"] == 100
    assert quantities["ESP8266"] == 200
    assert quantities["LM2596"] == 50
    assert quantities['0.96" OLED displays'] == 100
    assert quantities["DHT22"] == 25
    assert any("range" in note.text for note in notes)
    assert any("approximate" in note.text for note in notes)


def test_per_board_math_and_single_assorted_line():
    source = """
PROJECT A - Smart Thermostat (500 units):
- ESP32-WROOM-32D - 500 pcs
- Relay 5V 10A SPDT - 2 per board
PROJECT B - Security Panel (300 units):
- PIR sensor - 3 per unit
- LED RGB 5mm - 6 per unit
Common to both projects:
- Resistors 0805 assorted (10K, 4.7K, 1K) - 50,000 total
- TI LM358N or equivalent dual op-amp - 300 pcs
Delivery split: Project A by Aug 15, Project B by Sep 1.
""".strip()
    items = [
        LineItem(partNumber="ESP32-WROOM-32D", quantity=500),
        LineItem(partNumber="Relay 5V 10A SPDT", quantity=2),
        LineItem(partNumber="PIR sensor", quantity=3),
        LineItem(partNumber="LED RGB 5mm", quantity=6),
        LineItem(partNumber="10K resistor", quantity=16666),
        LineItem(partNumber="4.7K resistor", quantity=16667),
        LineItem(partNumber="1K resistor", quantity=16667),
        LineItem(partNumber="TI LM358N or equivalent dual op-amp", quantity=300),
    ]
    from datetime import datetime

    updated, due, instructions, notes = apply_policies(
        items,
        source,
        email_date=datetime(2026, 6, 12),
    )
    by_part = {item.partNumber: item for item in updated}
    assert by_part["Relay 5V 10A SPDT"].quantity == 1000
    assert "2 per board × 500 boards" in (by_part["Relay 5V 10A SPDT"].notes or "")
    assert by_part["PIR sensor"].quantity == 900
    assert by_part["LED RGB 5mm"].quantity == 1800
    assert "0805 resistors (10K, 4.7K, 1K)" in by_part
    assert by_part["0805 resistors (10K, 4.7K, 1K)"].quantity == 50000
    assert "10K resistor" not in by_part
    assert by_part["LM358N"].manufacturer == "TI"
    assert "or equivalent" in (by_part["LM358N"].notes or "")
    assert due == "2026-08-15"
    assert instructions and "2026-09-01" in instructions
    assert any("earlier" in note.text for note in notes)


def test_explicit_qty_overrides_a_wrong_guess():
    source = "- TI LM358N - Qty 500\nSN74HC595N    | Texas Instruments       | 200  | $0.50"
    items = [
        LineItem(partNumber="LM358N", manufacturer="TI", quantity=50),
        LineItem(partNumber="SN74HC595N", quantity=20),
    ]
    updated, _due, _instructions, _notes = apply_policies(items, source)
    assert updated[0].quantity == 500
    assert updated[1].quantity == 200


def test_single_explicit_date():
    dates = find_dates("Due date: March 15, 2026\nRush delivery required.")
    assert [item.isoformat() for item in dates] == ["2026-03-15"]


def test_confidence_subtracts_only_penalized_warnings():
    notes = [
        Note(text="LM358N: quantity was approximate (200)."),
        Note(text="The email contained an instruction-override block. It was quarantined and did not change the route.", penalize=False),
    ]
    assert apply_confidence(0.9, notes) == 0.85
    assert apply_confidence(0.02, [Note(text="x")] * 5) == 0.0
