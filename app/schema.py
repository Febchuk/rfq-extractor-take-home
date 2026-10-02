"""JSON contract returned by POST /ingest."""

from typing import Literal

from pydantic import BaseModel, Field


class Customer(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    company: str | None = None


class RequestInfo(BaseModel):
    dueDate: str | None = None
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    specialInstructions: str | None = None


class LineItem(BaseModel):
    partNumber: str
    manufacturer: str | None = None
    description: str | None = None
    quantity: int = 0
    targetPrice: float | None = None
    notes: str | None = None


class RfqContract(BaseModel):
    isRfq: Literal[True] = True
    confidence: float = Field(ge=0.0, le=1.0)
    customer: Customer
    request: RequestInfo
    lineItems: list[LineItem]
    warnings: list[str]


class NotRfqContract(BaseModel):
    isRfq: Literal[False] = False
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


Contract = RfqContract | NotRfqContract


class Note(BaseModel):
    """Internal warning. Only `text` is copied into the RFQ contract."""

    text: str
    penalize: bool = True
