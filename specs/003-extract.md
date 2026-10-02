# 003 — Extraction, quantity policy, and grounding

## What this is

For an email Jev called an RFQ, code chooses one extractor and then checks the lines. CSV rows are parsed. Prose, tables, and PDF text go to Gemini Flash. A PNG goes to the same model as an image. Policy code overwrites quantities and dates it can see in the source. Grounding flags invented parts. One Pro retry is allowed. Lines are kept.

## In scope

- CSV attachments become line items directly: part, manufacturer, quantity, target price, notes.
- `gemini-3.8-flash` for prose, tables, and PDF text, thinking `low`. The PNG uses the same model, thinking `medium`, and also returns a transcription.
- `gemini-3.1-pro-preview` runs once when a generated part number is absent from the source, or when a generative extract returns no lines.
- Quantity rules: range floor, stated hedge, per-board multiplication, one assorted-resistor line, one "or equivalent" line, earlier of two dates.
- Explicit `Qty N` and a table cell `| 200 |` overwrite a model quantity.
- Grounding is a normalized substring check against body, CSV, PDF text, and image transcription. Ambiguous parts get a Jev Noul. A yes probability of at least `0.7` clears the doubt. Between `0.35` and `0.65` the warning says the judgment is split.
- Confidence starts at the route confidence and subtracts `0.05` per penalized warning, then clamps to `0–1`. The injection warning is not penalized.
- Headers win for name and email. The signature company wins when the heuristic finds one.

## Out of scope

- A critic loop.
- Dropping a line that fails grounding.
- Catalog normalization. `TI` and `10K 0805` stay as written.
- Reading the PNG from Jev. Image grounding uses the model's transcription.
- HTTP and the dashboard.

## Verification

`pytest tests/test_policies.py` and the pipeline tests that use a fake extractor. No API key.

- Ranges `100-150`, `50 to 75`, and `25-30` store the floor. `roughly 200` and `~100` store that integer.
- `2 per board` on 500 units becomes `1000`. Three resistor splits collapse to one line at `50000`. `LM358N or equivalent` stays one line with manufacturer `TI`.
- Two dates resolve to `2026-08-15`.
- `LM358N` present, `USB connector` ambiguous, `NOTAREALPART9` absent.
- An absent part triggers exactly two extractor calls, Flash then Pro, and the line remains.
