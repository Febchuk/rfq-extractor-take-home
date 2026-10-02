# 001 — Email intake and the JSON contract

## What this is

The front of the pipeline. A raw `.eml` becomes a parsed message and, later, a JSON object an ERP can create. This spec covers the shape of that object and the code that reads the email. It does not call a model.

## In scope

- The RFQ contract: `isRfq`, `confidence`, `customer`, `request`, `lineItems`, `warnings`.
- The non-RFQ contract: `isRfq`, `confidence`, and one `reason`. No extra fields.
- Parsing one RFC822 message with the standard library: body, CSV attachment, text PDF, PNG bytes.
- Quarantine of obvious instruction-override blocks. The commercial body is what later steps read. The raw body is kept.
- Customer name and email from the `From` header. Phone from a regex. Company from the signature line above the email address.
- An in-memory inbox that forgets its contents when the process exits.
- The sample bundle: emails, `labels.json`, `parts-catalog.csv`, and `spec.pdf`.

## Out of scope

- Deciding whether the email is an RFQ.
- Extracting line items with a model.
- HTTP, the dashboard, catalog matching, and authentication.
- Excel attachments, a database, and a real ERP write.

## Verification

`pytest tests/test_parse.py` with no API keys.

- `rfq-07-restock.eml`: the override banner is removed from the commercial body and the three part lines remain.
- `rfq-04-csv-attachment.eml`: four CSV rows, including `LM317T` quantity 300 and target price `1.10`.
- `rfq-05-pdf-attachment.eml`: PDF text contains `STM32F407VGT6`. The body, not the PDF, contains `NEO-6M`.
- `rfq-08-image.eml`: the PNG bytes are kept and no CSV rows are invented.
