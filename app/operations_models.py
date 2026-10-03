from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID
from urllib.parse import urlsplit

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, field_validator


def utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def recorded_time(value: datetime) -> datetime:
    value = utc(value)
    if value > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("實際核對／收付時間不可在未來")
    return value


Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2, allow_inf_nan=False),
                  AfterValidator(lambda value: value.quantize(Decimal("0.01")))]
PositiveMoney = Annotated[Money, Field(gt=0)]
Moment = Annotated[AwareDatetime, AfterValidator(utc)]
RecordedTime = Annotated[AwareDatetime, AfterValidator(recorded_time)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Text = Annotated[str, Field(min_length=1, max_length=500)]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID


class Evidence(Command):
    reference: Text
    occurred_at: RecordedTime
    checked: Literal[True]


class QuoteAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    currency: Currency
    service_fee: Money = Decimal("0.00")
    discount: Money = Decimal("0.00")


class QuoteCreate(Command):
    title: Annotated[str, Field(min_length=1, max_length=160)]
    valid_until: Moment
    includes: Annotated[str, Field(min_length=1, max_length=4000)]
    excludes: Annotated[str, Field(min_length=1, max_length=4000)]
    adjustments: list[QuoteAdjustment] = Field(default_factory=list, max_length=10)
    costs: dict[str, Money | None] = Field(default_factory=dict, max_length=10)


class QuoteDecision(Evidence):
    amend: bool = False
    reason: Annotated[str, Field(max_length=1000)] = ""


class Links(Command):
    quote_id: str | None = None
    booking_id: str | None = None
    document_id: str | None = None


TaskKind = Literal["reply", "quote_followup", "deposit", "balance", "ticketing", "cancellation", "document", "pretrip", "change", "refund", "other"]


class WorkItemCreate(Links):
    kind: TaskKind
    title: Text
    owner: Annotated[str, Field(min_length=1, max_length=100)]
    due_at: Moment
    source: Text
    notes: Annotated[str, Field(max_length=2000)] = ""


class WorkItemPatch(Command):
    expected_revision: int = Field(ge=1)
    status: Literal["open", "done", "cancelled"] | None = None
    due_at: Moment | None = None
    owner: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    notes: Annotated[str, Field(max_length=2000)] | None = None
    reason: Text


class BookingCreate(Evidence):
    kind: Literal["flight", "hotel"]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    supplier: Annotated[str, Field(min_length=1, max_length=160)]
    confirmation_number: Annotated[str, Field(min_length=1, max_length=100)]
    customer_details: Annotated[str, Field(min_length=1, max_length=4000)]


class BookingRebind(Evidence):
    reason: Text
    customer_details: Annotated[str, Field(min_length=1, max_length=4000)]


class VoidRecord(Evidence):
    reason: Text


class LedgerCreate(Evidence):
    kind: Literal["customer_receipt", "customer_refund", "supplier_payment", "supplier_refund"]
    amount: PositiveMoney
    currency: Currency
    booking_id: str | None = None
    memo: Annotated[str, Field(max_length=1000)] = ""


DocumentKind = Literal["e_ticket", "hotel_voucher", "itinerary", "visa_check", "insurance", "other"]


def validate_customer_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("文件連結需為不含帳密的 HTTPS 網址")
    return value


class DocumentCreate(Command):
    kind: DocumentKind
    title: Text
    required: bool = True
    booking_id: str | None = None


class DocumentPatch(Evidence):
    expected_revision: int = Field(ge=1)
    status: Literal["missing", "ready"]
    customer_text: Annotated[str, Field(max_length=6000)] = ""
    customer_url: Annotated[str | None, Field(max_length=2000)] = None

    required: bool | None = None
    booking_id: str | None = None
    reason: Annotated[str, Field(max_length=500)] = ""

    _url = field_validator("customer_url")(validate_customer_url)


class PackCreate(Command):
    title: Annotated[str, Field(min_length=1, max_length=200)]


class PackDelivery(Evidence):
    channel: Annotated[str, Field(min_length=1, max_length=100)]
