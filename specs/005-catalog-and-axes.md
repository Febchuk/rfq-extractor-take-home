# 005 — Catalog sidecar and two-axis disagreement

## What this is

Two extra readings that stay off the JSON contract. A parts catalog can suggest a row, refuse a package, or offer a description match. A second probability says whether the email lists parts, separate from whether it asks for a quote. The inbox shows both numbers only when they disagree.

## In scope

- Load `samples/parts-catalog.csv` after quantity policy and grounding.
- An exact MPN shows that catalog row. `partNumber` and `manufacturer` stay as written, including `TI`.
- A package stem such as `LM358` lists `LM358N`, `LM358D`, and `LM358AN`, chooses none, and adds a warning that the package was not guessed.
- Description overlap, such as `10K 0805` against `RC0805FR-0710KL`, is a suggestion. It is not copied into `partNumber`.
- Manufacturer aliases `TI`, `ON Semi`, and `ST` appear only in the sidecar.
- A descriptive line with no part-number shape, such as `Relay 5V 10A SPDT`, gets no catalog warning.
- The same Jev route call also asks a Noul, `has_parts`: does the commercial email name specific parts with quantities or prices?
- `P(rfq)` is read from the route choice's probability map. It is not the winning label's confidence.
- The inbox row shows both probabilities when one is at least `0.5` and the other is below `0.5`. An RFQ whose scores agree does not get that extra cell.
- Skip-reason templates stay as they are.
- The detail page shows the catalog sidecar under each line.
- The README diagram covers parse, quarantine, the Jev route call, the CSV / Flash / image branch, grounding, the single Pro retry, and these two sidecar outputs.

## Out of scope

- Rewriting `partNumber` or `manufacturer` in the contract.
- A new JSON field for catalog matches or the two probabilities.
- Changing the templated non-RFQ sentences.
- Letting the injection Noul delete text or flip `isRfq`.

## Verification

`pytest` with no API key.

- `LM358` lists the three catalog packages, chooses none, and warns. The written part stays `LM358`.
- `LM358N` with manufacturer `TI` keeps both contract fields and notes the alias only on the sidecar.
- `10K 0805` suggests `RC0805FR-0710KL` and does not replace the part number.
- `Relay 5V 10A SPDT` produces no catalog warning.
- An inbox row with `P(rfq)` below `0.5` and `has_parts` at least `0.5` shows both probabilities. A row where both are at least `0.5` does not.

With both keys set, ingest the newsletter and the order confirmation and confirm both probabilities show on those rows. Ingest a normal RFQ and confirm the pair is absent.
