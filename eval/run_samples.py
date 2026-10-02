"""Run every sample through the live pipeline and diff the labeled ones."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.env import load_dotenv
from app.pipeline import run

load_dotenv(ROOT / ".env")

LABELED = {
    "rfq-01-bullet.eml",
    "rfq-02-table.eml",
    "rfq-04-csv-attachment.eml",
    "rfq-05-pdf-attachment.eml",
    "not-an-rfq-01-order-confirmation.eml",
}


def main() -> int:
    labels = json.loads((ROOT / "samples" / "labels.json").read_text(encoding="utf-8"))
    failures: list[str] = []
    for path in sorted((ROOT / "samples").glob("*.eml")):
        outcome = run(path.read_text(encoding="utf-8"))
        actual = outcome.contract.model_dump(mode="json")
        print(f"\n== {path.name} ==")
        print(json.dumps(actual, indent=2))
        expected = labels.get(path.name)
        if path.name not in LABELED or expected is None:
            continue
        mismatches = _diff(expected, actual)
        if mismatches:
            failures.append(path.name)
            print("MISMATCH")
            for line in mismatches:
                print(" -", line)
        else:
            print("labeled fields match")
    if failures:
        print("\nFailed:", ", ".join(failures))
        return 1
    print("\nAll labeled samples matched.")
    return 0


def _diff(expected: dict, actual: dict) -> list[str]:
    mismatches: list[str] = []
    if expected.get("isRfq") != actual.get("isRfq"):
        mismatches.append(f"isRfq expected {expected.get('isRfq')} got {actual.get('isRfq')}")
    if not expected.get("isRfq"):
        if not actual.get("reason"):
            mismatches.append("missing reason")
        return mismatches
    for field in ("name", "email", "phone", "company"):
        if expected["customer"].get(field) != actual["customer"].get(field):
            mismatches.append(
                f"customer.{field} expected {expected['customer'].get(field)!r} "
                f"got {actual['customer'].get(field)!r}"
            )
    expected_lines = [
        (item["partNumber"], item["quantity"]) for item in expected["lineItems"]
    ]
    actual_lines = [
        (item["partNumber"], item["quantity"]) for item in actual["lineItems"]
    ]
    if expected_lines != actual_lines:
        mismatches.append(f"line items expected {expected_lines} got {actual_lines}")
    return mismatches


if __name__ == "__main__":
    raise SystemExit(main())
