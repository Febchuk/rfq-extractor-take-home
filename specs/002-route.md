# 002 — Route classification

## What this is

One Jev call decides what kind of email this is, whether it tries to override the assistant, and how urgent a quote would be. Code turns a non-RFQ label into a fixed reason sentence. Gemini is not called on that path.

## In scope

- One `system_one` request with three questions over the parsed email:
  - Choice `route`: `rfq`, `order_confirmation`, `newsletter_or_announcement`, `other_not_rfq`. The route question sees only the commercial copy.
  - Noul `injection`: the raw copy, including any quarantined banner. A score of at least `0.7` adds a warning. It does not change the route.
  - Score `priority`: `low`, `medium`, `high`, `urgent`. "Rush delivery" is `high`. A stopped line is `urgent`. Below `0.5` confidence, store `medium`.
- Templated reasons. The three non-RFQ labels map to fixed sentences. Low route confidence and an ignored injection attempt are appended sentences, not new JSON fields.
- A non-RFQ result is returned even when route confidence is below `0.5`. Soft confidence does not turn a newsletter into line items.

## Out of scope

- Generating the reason with a model.
- Extracting parts.
- Using the injection score to delete text the quarantine regex missed.
- Rewriting the route when the injection score is high.

## Verification

Unit tests construct a `Classification` and call `reason_for`. No API key.

- `order_confirmation` and `newsletter_or_announcement` return their template sentences.
- Confidence below `0.5` appends "Classification confidence was below 0.5."
- A quarantined flag, or an injection probability of at least `0.7`, appends "An instruction-override attempt was ignored."
- The pipeline test for the newsletter sample uses a fake classifier and asserts the extractor is not called.
