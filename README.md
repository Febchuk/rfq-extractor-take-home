# RFQ ingest

A small service that turns one raw RFQ email into the JSON contract an ERP can create. Code owns the workflow. [Jev](https://docs.typesafe.ai/concepts/system-one.md) classifies and checks doubtful parts. Gemini extracts only when the parts list is unstructured text or a scanned image.

Time spent: one sitting for the design pass and the implementation, aimed at the four-hour budget.

## Run

Python 3.13. The TypeSafe SDK did not install on the system Python 3.9.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# set GEMINI_API_KEY and TYPESAFE_API_KEY
uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000 and upload or paste an `.eml`. The inbox keeps what you ingested until the process exits.

`POST /ingest` with the raw message as the body (`text/plain` or `message/rfc822`) returns the contract JSON.

```bash
curl -s -X POST http://127.0.0.1:8000/ingest \
  -H 'content-type: message/rfc822' \
  --data-binary @samples/rfq-01-bullet.eml
```

If a key is missing the server still starts. `/ingest` returns an error instead of a contract. Parser and CSV tests do not need keys.

```bash
pytest
python -m eval.run_samples   # live; needs both keys
```

`eval/run_samples.py` prints every sample. For the five emails in `samples/labels.json` it checks `isRfq`, the customer fields, and each line's part number and quantity. Non-RFQ reasons are templates, so the wording is not compared. The other five samples are printed for review.

Set only `GEMINI_API_KEY`. If `GOOGLE_API_KEY` is also set, the Gemini SDK uses that one instead.

## What it does

```
parse MIME → quarantine override text → Jev route / injection / priority
  → skip, or CSV rows, or Gemini text, or Gemini on the PNG
  → code fixes quantities and dates → exact grounding
  → Jev on ambiguous parts → one Pro retry if a part is missing
  → contract
```

This is the [custom logic pattern](https://docs.cloud.google.com/wiki/choose-design-pattern-agentic-ai-system): the steps are known, so a model does not choose the next step. A new attachment type is a code change.

## Decisions

**Orchestration is custom logic, not a model.** A ReAct loop or a generative coordinator would adapt to a new attachment without a code change. They also add latency, an untested tool loop, and a place for the injected instructions in `rfq-07-restock.eml` to steer the workflow.

**Jev classifies and verifies. Gemini Flash extracts.** One Jev call returns the route, an injection probability, and a priority score, so newsletters and order confirmations never hit Gemini. Jev cannot emit an open parts list or read pixels, so prose, PDF text, and the PNG go to `gemini-3.8-flash`. The same Flash model reads the scan. A separate vision model would be a third vendor for one PNG. `gemini-3.1-pro-preview` runs only when grounding says a part number is not in the source. That Pro id is still a preview. Text extraction uses thinking `low`. The scan, and the Pro retry, use thinking `medium`.

**Non-RFQ reasons are templates.** The route choice maps to a fixed sentence. The skip path makes no generative call. The sentence will not match `labels.json` word for word. If route confidence is below 0.5 the email is still not extracted, and the reason says so.

**Headers, CSV, and stated quantities stay in code.** The `From` header supplies name and email. A phone regex supplies the phone. The signature line above the email supplies the company when it is there. `csv` parses the attachment, and those rows are the line items. `Qty N` and a table cell of the form `| 200 |` overwrite a model quantity. Per-board factors are multiplied in code (`2 per board` × `500` → `1000`) and the formula is kept in notes. The cost: a messy CSV or an unusual "per board" phrase falls through to the model, and the result carries a warning.

**Injection is quarantined, then still classified.** A banner that tells the model to ignore its rules (the block in `rfq-07`) is removed from what Jev's route question and Gemini see. The commercial body stays. Jev's injection question still sees the raw text, so the warning does not depend on the regex alone. A high injection probability does not flip `isRfq`. This filter is narrow. It will miss a subtler attack. It is not a sandbox.

**Grounding is exact match, then Jev, then one retry. Lines are kept.** A normalized substring check is free and catches a part the source does not contain. Jev runs only when that check is ambiguous (some tokens match, the whole part number does not). A yes probability of at least 0.7 clears the doubt. Between 0.35 and 0.65 the warning says the judgment is split. Those cutoffs come from the TypeSafe cascade notes and still need to be checked on real mail; they are not universal. If a part is simply absent, Gemini Pro extracts once. If it is still absent, the line stays, a warning is attached, and confidence drops. A critic loop would raise quality and can run away on cost. Dropping the line would hide the miss from the operator.

**Image grounding checks the model's own transcription.** The vision call returns the table text and the line items. The substring check compares them. Jev cannot see the PNG. Those warnings are weaker than warnings on an email whose text we parsed ourselves. An independent OCR pass would be a second witness.

**Quantity uses the stated floor.** A range such as `100-150` or `50 to 75` stores the lower integer and keeps the range in notes. `roughly 200` and `~100` store that integer and warn that it was approximate. The assorted resistor total stays one line at `50000` because splitting `10K`, `4.7K`, and `1K` would invent three quantities. `LM358N or equivalent` stays one line. Two delivery dates: `dueDate` is the earlier one (`2026-08-15` on the multi-project sample), and both dates are written into `specialInstructions`. Quoting the high end, or the later date, is the other defensible call. The floor avoids overstating demand, and the warning keeps the original wording.

**Priority comes from Jev.** The score levels are: no time pressure, a normal quote, rush or a firm near date, and a stopped line or same-day emergency. "Rush delivery" is the third level, `high`. If that score's confidence is below 0.5, the stored priority is `medium`. Asking Gemini for priority as well would repeat a closed-set judgment.

**Catalog aliases stay as written.** `TI` stays `TI`. `10K 0805` stays `10K 0805`. Rewriting them to `samples/parts-catalog.csv` would disagree with the labeled answers.

**Confidence is a formula.** Start from Jev's route confidence. Subtract `0.05` for each warning about a line item, quantity, date, or equivalent. Do not subtract for the injection warning or the low route-confidence warning. Clamp to 0–1 and round to two decimals. A model's own probability would read as more precise than this pipeline is.

**The dashboard shows warnings and does not block.** `POST /ingest` always returns the contract when the models respond. Nothing waits on a person. A hold before an ERP write is the human-in-the-loop pattern, and it needs a queue and auth, which are out of scope. The non-RFQ JSON has `isRfq`, `confidence`, and `reason` only. Uncertainty on a skip is folded into `reason` so the contract does not grow a field.

**Storage is process memory.** Restart clears the inbox. A file or a database would survive restart and is unnecessary for this demo.

## With more time

- Resolve part numbers and manufacturer aliases against `samples/parts-catalog.csv`, beside the contract, without rewriting the labeled fields.
- OCR the scan with a second tool so image grounding is not the same model checking itself.
- Hold the ERP create until a person clears warnings.
- Replace the banner filter with a real injection sandbox.
- Persist the inbox.

Not in that list: Excel attachments, authentication, deployment, or a multi-user store.
