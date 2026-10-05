"""Evidence-bearing commands for manual service work; no provider/payment execution."""
from decimal import Decimal
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.operations_models import Evidence, Money, Moment, PositiveMoney, Text, Currency, validate_customer_url

OrderKind = Literal['change', 'cancellation', 'refund', 'incident']
LedgerKind = Literal['customer_receipt', 'customer_refund', 'supplier_payment', 'supplier_refund']


class ServiceOrderCreate(Evidence):
    kind: OrderKind
    title: Text
    request_details: Annotated[str, Field(min_length=1, max_length=4000)]
    contact: Annotated[str, Field(max_length=500)] = ''
    owner: Annotated[str, Field(min_length=1, max_length=100)]
    due_at: Moment
    urgency: Literal['normal', 'urgent'] = 'normal'
    booking_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator('booking_ids')
    @classmethod
    def unique_bookings(cls, value):
        if len(set(value)) != len(value) or any(not item for item in value):
            raise ValueError('請選不重複的有效訂購')
        return value


class ServiceOrderCommand(Evidence):
    expected_revision: int = Field(ge=1)


class ServiceOrderPatch(ServiceOrderCommand):
    owner: Annotated[str, Field(min_length=1, max_length=100)]
    due_at: Moment
    urgency: Literal['normal', 'urgent']
    contact: Annotated[str, Field(max_length=500)] = ''
    reason: Text


class OrderAmounts(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    # These are approved TOTALS, already including the informational fee breakdown.
    # No automatic statutory percentages, conversion or additional fee summation.
    currency: Currency
    customer_receipt: Money = Decimal('0.00')
    customer_refund: Money = Decimal('0.00')
    supplier_payment: Money = Decimal('0.00')
    supplier_refund: Money = Decimal('0.00')
    supplier_fee: Money = Decimal('0.00')
    agency_fee: Money = Decimal('0.00')
    final_customer_due: Money


class ServiceAssessment(ServiceOrderCommand):
    supplier_reply: Annotated[str, Field(min_length=1, max_length=4000)]
    proposal: Annotated[str, Field(min_length=1, max_length=4000)]
    terms_reference: Text
    terms_url: Annotated[str | None, Field(max_length=2000)] = None
    valid_until: Moment
    amounts: list[OrderAmounts] = Field(default_factory=list, max_length=10)
    reason: Text

    _url = field_validator('terms_url')(validate_customer_url)

    @field_validator('amounts')
    @classmethod
    def unique_currencies(cls, values):
        if len({item.currency for item in values}) != len(values):
            raise ValueError('每個幣別請填一列，不可重複')
        return values


class ServiceDecision(ServiceOrderCommand):
    assessment_revision: int = Field(ge=1)
    decision: Literal['approved', 'declined']
    customer_reply: Annotated[str, Field(min_length=1, max_length=4000)]


class ServiceNote(ServiceOrderCommand):
    stage: Literal['note', 'contact_supplier', 'contact_customer', 'safety_assistance', 'correction']
    message: Annotated[str, Field(min_length=1, max_length=4000)]


class ServiceStart(ServiceOrderCommand):
    stage: Literal['start']


class ServiceSupplierResult(ServiceOrderCommand):
    stage: Literal['supplier_result']
    outcome: Literal['confirmed', 'declined']
    details: Annotated[str, Field(min_length=1, max_length=4000)]
    booking_revisions: dict[str, int] = Field(default_factory=dict, max_length=20)
    result_booking_ids: list[Annotated[str, Field(min_length=1,max_length=100)]] = Field(default_factory=list, max_length=20)


class ServiceRebindResult(ServiceOrderCommand):
    stage: Literal['rebind_result']
    details: Annotated[str, Field(min_length=1,max_length=4000)]
    result_booking_ids: list[Annotated[str, Field(min_length=1,max_length=100)]] = Field(min_length=1,max_length=20)


class ServiceWithdraw(ServiceOrderCommand):
    stage: Literal['withdraw']
    reason: Text


class ServiceVoidSettlement(ServiceOrderCommand):
    stage: Literal['void_settlement']
    entry_id: Annotated[str, Field(min_length=1,max_length=100)]
    reason: Text


ServiceProgress = Annotated[Union[ServiceNote, ServiceStart, ServiceSupplierResult,
                                  ServiceWithdraw, ServiceVoidSettlement, ServiceRebindResult], Field(discriminator='stage')]


class ServiceSettlement(ServiceOrderCommand):
    kind: LedgerKind
    amount: PositiveMoney
    currency: Currency
    memo: Annotated[str, Field(max_length=1000)] = ''


class ServiceResolve(ServiceOrderCommand):
    summary: Annotated[str, Field(min_length=1, max_length=4000)]
    end_trip: bool = False
    customer_notified_checked: Literal[True]


class ServiceReopen(ServiceOrderCommand):
    reason: Text
