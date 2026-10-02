from app.catalog import annotate
from app.schema import LineItem


def test_package_stem_lists_three_and_chooses_none():
    item = LineItem(partNumber="LM358", manufacturer="TI", quantity=100)
    matches, notes = annotate([item])
    match = matches[0]
    assert item.partNumber == "LM358"
    assert item.manufacturer == "TI"
    assert match.kind == "package"
    assert match.chosen is None
    assert [row.mpn for row in match.candidates] == ["LM358N", "LM358D", "LM358AN"]
    assert notes and "not guessed" in notes[0].text
    assert "LM358N" in notes[0].text and "LM358D" in notes[0].text and "LM358AN" in notes[0].text


def test_exact_mpn_does_not_rewrite_the_manufacturer():
    item = LineItem(partNumber="LM358N", manufacturer="TI", quantity=500)
    matches, notes = annotate([item])
    match = matches[0]
    assert item.partNumber == "LM358N"
    assert item.manufacturer == "TI"
    assert match.kind == "exact"
    assert match.chosen is not None
    assert match.chosen.mpn == "LM358N"
    assert match.chosen.manufacturer == "Texas Instruments"
    assert match.manufacturer_alias == "TI is an alias of Texas Instruments"
    assert notes == []


def test_description_suggestion_does_not_replace_the_part_number():
    item = LineItem(partNumber="10K 0805", quantity=5000)
    matches, notes = annotate([item])
    match = matches[0]
    assert item.partNumber == "10K 0805"
    assert match.kind == "description"
    assert match.chosen is None
    assert match.candidates[0].mpn == "RC0805FR-0710KL"
    assert notes == []


def test_descriptive_line_without_an_mpn_shape_has_no_warning():
    item = LineItem(partNumber="Relay 5V 10A SPDT", quantity=10)
    matches, notes = annotate([item])
    assert matches[0].kind == "none"
    assert matches[0].candidates == []
    assert matches[0].warning is None
    assert notes == []


def test_short_manufacturer_aliases_stay_on_the_sidecar():
    items = [
        LineItem(partNumber="BC547", manufacturer="ON Semi", quantity=1000),
        LineItem(partNumber="STM32F103C8T6", manufacturer="ST", quantity=50),
    ]
    matches, notes = annotate(items)
    assert items[0].manufacturer == "ON Semi"
    assert items[1].manufacturer == "ST"
    assert matches[0].kind == "exact"
    assert matches[0].manufacturer_alias == "ON Semi is an alias of ON Semiconductor"
    assert matches[1].manufacturer_alias == "ST is an alias of STMicroelectronics"
    assert notes == []
