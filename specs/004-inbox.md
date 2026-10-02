# 004 — Inbox API and dashboard

## What this is

The operator surface. `POST /ingest` accepts one raw email and returns the contract. A single-page inbox lists what was ingested and a detail page shows the fields. Restarting the process clears the list.

## In scope

- `POST /ingest` with a raw body (`text/plain` or `message/rfc822`) returns the contract JSON.
- A browser form (file or pasted text) posts the same endpoint and redirects to the detail page.
- `GET /` lists subject, sender, RFQ or not, confidence, and warning count.
- `GET /rfqs/{id}` shows customer, request, line items, warnings, and the contract JSON. A non-RFQ shows the reason.
- A missing key or extractor failure is a clear error. The form renders an HTML error page. The raw API returns JSON. A failed ingest is not stored.
- The server starts when `GEMINI_API_KEY` or `TYPESAFE_API_KEY` is missing.
- README: how to run, the decisions, and what to do with more time.

## Out of scope

- Authentication, accounts, and a hold before an ERP write.
- Persistence beyond process memory.
- Catalog suggestions and a second probability on the inbox row. Those are spec 005.
- Deployment.

## Verification

`pytest tests/test_pipeline.py` with no API key.

- A raw `POST /ingest` of a non-RFQ returns JSON with `isRfq: false` and a `reason`, and no `warnings` field.
- The inbox HTML lists that message as "Not an RFQ" and the detail page shows the reason.
- A form post with no `TYPESAFE_API_KEY` returns 503 and the HTML error "TYPESAFE_API_KEY is not set".
