from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ManualOptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["flight", "hotel"]
    supplier_name: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    total_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="TWD", pattern=r"^[A-Za-z]{3}$")
    details: str = Field(min_length=1, max_length=2400)
    conditions: str = Field(min_length=1, max_length=1600)
    source_reference: str = Field(min_length=1, max_length=500)
    source_url: str | None = Field(default=None, max_length=1000)
    observed_at: datetime
    valid_until: datetime | None = None
    confirmed_for_case: Literal[True]

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("source_url")
    @classmethod
    def safe_source_url(cls, value: str | None) -> str | None:
        if not value:
            return None
        url = urlsplit(value)
        if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
            raise ValueError("來源網址需為不含帳密的 http / https 網址")
        return value

    @model_validator(mode="after")
    def validate_observation(self) -> "ManualOptionCreate":
        for value in [self.observed_at, self.valid_until]:
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("查詢與有效時間需包含時區")
        if self.observed_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("查詢時間不可在未來")
        if self.valid_until is not None and self.valid_until <= self.observed_at:
            raise ValueError("有效期限必須晚於查詢時間")
        return self


class CaseOptionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option_id: str = Field(min_length=1, max_length=300)
