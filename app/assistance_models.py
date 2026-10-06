"""Private passenger fulfilment, customer history and explicit reminder commands."""

from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.operations_models import Evidence, Moment, Text

Identifier = Annotated[str, Field(min_length=1, max_length=100)]
RequestKind = Literal["seat", "meal", "wheelchair", "baggage", "other"]


def meaningful_body(value):
    if not value.strip():
        raise ValueError("請填寫訊息內容")
    return value


class SpecialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    value: Annotated[str, Field(max_length=500)] = ""
    status: Literal["not_requested", "requested", "confirmed", "declined"] = (
        "not_requested"
    )
    supplier_reference: Annotated[str, Field(max_length=500)] = ""

    @model_validator(mode="after")
    def request_has_content(self):
        if self.status != "not_requested" and not self.value:
            raise ValueError("請填特殊需求內容，再選擇處理狀態")
        return self


class TravellerService(Evidence):
    traveller_id: Identifier
    booking_id: Identifier
    traveller_revision: int = Field(ge=1)
    booking_revision: int = Field(ge=1)
    expected_revision: int | None = Field(default=None, ge=1)
    segment_label: Annotated[str, Field(min_length=1, max_length=160)]
    ticket_number: Annotated[str, Field(max_length=40)] = ""
    requests: dict[RequestKind, SpecialRequest] = Field(
        default_factory=dict, max_length=5
    )
    notes: Annotated[str, Field(max_length=2000)] = ""


class RecordEvidence(Evidence):
    expected_revision: int = Field(ge=1)


class CustomerProfile(Evidence):
    display_name: Annotated[str, Field(min_length=1, max_length=160)]
    phone: Annotated[str, Field(max_length=80)] = ""
    email: Annotated[str, Field(max_length=254)] = ""
    notes: Annotated[str, Field(max_length=4000)] = ""
    expected_revision: int | None = Field(default=None, ge=1)

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        import re

        if value and not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", value):
            raise ValueError("請填完整 Email 地址")
        return value

    @field_validator("display_name", "email")
    @classmethod
    def no_header_lines(cls, value):
        if "\r" in value or "\n" in value:
            raise ValueError("姓名與 Email 不可含換行")
        return value


class CustomerConsent(RecordEvidence):
    channel: Literal["email"] = "email"
    granted: bool


class CustomerLink(Evidence):
    customer_id: Identifier
    expected_revision: int = Field(ge=0)
    reason: Text


class CommunicationCreate(Evidence):
    kind: Literal["draft", "incoming", "outgoing", "contact", "complaint"]
    channel: Literal["manual", "email", "line", "phone", "in_person"] = "manual"
    body: Annotated[
        str,
        StringConstraints(strip_whitespace=False),
        AfterValidator(meaningful_body),
        Field(min_length=1, max_length=8000),
    ]
    owner: Annotated[str, Field(min_length=1, max_length=100)]
    followup_at: Moment | None = None
    service_order_id: Identifier | None = None
    corrects_id: Identifier | None = None


class CommunicationPatch(RecordEvidence):
    body: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=False),
            AfterValidator(meaningful_body),
            Field(min_length=1, max_length=8000),
        ]
        | None
    ) = None
    owner: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    followup_at: Moment | None = None
    status: Literal["open", "resolved"] | None = None

    @model_validator(mode="after")
    def explicit_patch(self):
        if any(
            name in self.model_fields_set and getattr(self, name) is None
            for name in ("body", "owner", "status")
        ):
            raise ValueError("內容、負責人與狀態不可清空")
        if not self.model_fields_set.intersection(
            {"body", "owner", "followup_at", "status"}
        ):
            raise ValueError("請指定要更新的內容或處理資料")
        return self


class CommunicationSent(RecordEvidence):
    actually_sent: Literal[True]


class ReminderRule(Evidence):
    source_kind: Literal["work_item", "service_order"]
    source_id: Identifier
    source_revision: int = Field(ge=1)
    channel: Literal["email", "line"]
    recipient_kind: Literal["staff", "customer"]
    recipient: Annotated[str, Field(max_length=254)] = ""
    customer_id: Identifier | None = None
    customer_revision: int | None = Field(default=None, ge=1)
    consent_revision: int | None = Field(default=None, ge=1)
    offset_minutes: int = Field(default=60, ge=0, le=60 * 24 * 30)
    repeat_hours: Literal[0, 24] = 0
    body: Annotated[
        str,
        StringConstraints(strip_whitespace=False),
        AfterValidator(meaningful_body),
        Field(min_length=1, max_length=2000),
    ]
    enabled: bool = False
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def explicit_recipient(self):
        if self.recipient_kind == "customer":
            if self.channel != "email":
                raise ValueError(
                    "客人 LINE 尚未綁定；請使用 Email，LINE 提醒目前供員工使用"
                )
            if not all(
                (self.customer_id, self.customer_revision, self.consent_revision)
            ):
                raise ValueError("請核對案件的客戶資料與 Email 接收同意")
        elif self.enabled and not self.recipient:
            raise ValueError("請選已設定的員工接收帳號")
        return self


class ReminderConfirmation(RecordEvidence):
    decision: Literal["accepted", "retry", "cancel"]
    duplicate_risk_checked: bool = False

    @model_validator(mode="after")
    def explicit_retry(self):
        if self.decision == "retry" and not self.duplicate_risk_checked:
            raise ValueError("請先核對寄送結果，並確認重試可能造成重複訊息")
        return self
