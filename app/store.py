"""Process-local inbox. Restarting the server clears it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from app.schema import Contract


@dataclass
class Record:
    id: str
    subject: str
    sender: str
    ingested_at: datetime
    contract: Contract
    source_name: str | None = None

    @property
    def warning_count(self) -> int:
        warnings = getattr(self.contract, "warnings", None)
        return len(warnings or [])


class Store:
    def __init__(self) -> None:
        self._records: list[Record] = []
        self._lock = Lock()

    def add(
        self,
        *,
        subject: str,
        sender: str,
        contract: Contract,
        source_name: str | None = None,
    ) -> Record:
        record = Record(
            id=uuid4().hex[:12],
            subject=subject or "(no subject)",
            sender=sender,
            ingested_at=datetime.now(timezone.utc),
            contract=contract,
            source_name=source_name,
        )
        with self._lock:
            self._records.insert(0, record)
        return record

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def list(self) -> list[Record]:
        with self._lock:
            return list(self._records)

    def get(self, record_id: str) -> Record | None:
        with self._lock:
            for record in self._records:
                if record.id == record_id:
                    return record
        return None


store = Store()
