from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID
from urllib.parse import urlsplit

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


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


class CaseLifecycle(Evidence):
    expected_state: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    reason: Text


class CaseClose(CaseLifecycle):
    outcome: Literal["completed", "withdrawn"]
    supplier_settlement_checked: Literal[True] | None = None
    withdraw_adoption_checked: Literal[True] | None = None

    @model_validator(mode="after")
    def require_settlement_check(self):
        if self.outcome == "completed" and self.supplier_settlement_checked is not True:
            raise ValueError("完成業務結案前，請確認供應商款項與後續服務均已核對")
        if self.outcome == "completed" and self.withdraw_adoption_checked is not None:
            raise ValueError("完成結案不可撤回報價採用")
        if self.outcome == "withdrawn" and self.supplier_settlement_checked is not None:
            raise ValueError("未成交結案不可填完成結算標示")
        return self


class CaseReopen(CaseLifecycle):
    pass


class SearchAbandon(Evidence):
    reason: Text
    expected_updated_at: Annotated[str, Field(min_length=1, max_length=100)]
    worker_stopped_checked: Literal[True]


class TravellerData(Command):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    category: Literal["adult", "child", "infant"]
    date_of_birth: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    passport_number: Annotated[str, Field(min_length=1, max_length=40)]
    passport_expiry: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    nationality: Annotated[str, Field(min_length=2, max_length=80)]
    expected_revision: int | None = Field(default=None, ge=1)

    @field_validator("date_of_birth", "passport_expiry")
    @classmethod
    def real_date(cls, value):
        from datetime import date
        parsed = date.fromisoformat(value)
        if value != parsed.isoformat():
            raise ValueError("請填有效日期")
        return value


class RosterVerify(Evidence):
    expected_state: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class AttachmentUpload(Command):
    expected_revision: int = Field(ge=1)
    filename: Annotated[str, Field(min_length=1, max_length=160)]
    media_type: Literal["application/pdf", "image/jpeg", "image/png"]
    size: int = Field(gt=0, le=10 * 1024 * 1024)
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class AttachmentArchive(Evidence):
    expected_revision: int = Field(ge=1)
    reason: Text


class WorkAcknowledgement(Evidence):
    expected_revision: int = Field(ge=1)


class WorkHandover(Evidence):
    items: dict[str, int] = Field(min_length=1, max_length=50)
    owner: Annotated[str, Field(min_length=1, max_length=100)]
    reason: Text

    @field_validator("items")
    @classmethod
    def revisions(cls, value):
        if any(not key or revision < 1 for key, revision in value.items()):
            raise ValueError("請選有效待辦")
        return value
