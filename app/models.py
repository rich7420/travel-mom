from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class CaseStatus(StrEnum):
    NEW = "new"
    INTAKE = "intake"
    QUOTING = "quoting"
    BOOKING = "booking"
    CONFIRMED = "confirmed"
    TRAVELLING = "travelling"
    CLOSED = "closed"


class TripCaseCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=80)
    destination: str | None = None
    origin: str | None = "TPE"
    depart_date: date | None = None
    return_date: date | None = None
    adults: int = Field(default=1, ge=1, le=50)
    children: int = Field(default=0, ge=0, le=50)
    budget_twd: int | None = Field(default=None, ge=0)
    notes: str = ""


class TripCase(TripCaseCreate):
    id: str
    status: CaseStatus = CaseStatus.NEW
    created_at: str
    updated_at: str


class GuidedReply(BaseModel):
    text: str
    options: list[str] = Field(default_factory=list)
    done: bool = False
    case_id: str | None = None
    next_field: str | None = None
    progress_current: int = 0
    progress_total: int = 0
    can_back: bool = False
    saved: bool = True


class ChannelReply(BaseModel):
    text: str
    options: list[str] = Field(default_factory=list)
    case_id: str | None = None
    source: str = "router"


class PriceObservation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("price"))
    case_id: str | None = None
    kind: str
    source_name: str
    source_url: str | None = None
    currency: str = "TWD"
    base_amount: int = Field(ge=0)
    taxes: int = Field(default=0, ge=0)
    mandatory_fees: int = Field(default=0, ge=0)
    total_amount: int = Field(ge=0)
    fare_or_room_type: str = ""
    baggage_or_meal: str = ""
    cancellation_or_change: str = ""
    observed_at: str = Field(default_factory=now_iso)
    valid_until: str | None = None
    evidence_note: str = "DEMO - not customer safe"
    customer_safe: bool = False


class BrowserTaskKind(StrEnum):
    FLIGHT_SEARCH = "flight_search"
    HOTEL_DISCOVERY = "hotel_discovery"
    HOTEL_SEARCH = "hotel_search"
    HOTEL_REVALIDATE = "hotel_revalidate"
    HOTEL_PREPARE_BOOKING = "hotel_prepare_booking"
    REVALIDATE_PRICE = "revalidate_price"
    PREPARE_BOOKING = "prepare_booking"


class BrowserTaskCreate(BaseModel):
    case_id: str | None = None
    search_run_id: str | None = None
    parent_task_id: str | None = None
    parent_option_id: str | None = None
    kind: BrowserTaskKind
    source_url: str
    instructions: str
    provider_code: str | None = None
    expected_schema: str | None = None


class BrowserTask(BaseModel):
    id: str
    case_id: str | None
    search_run_id: str | None = None
    parent_task_id: str | None = None
    parent_option_id: str | None = None
    kind: BrowserTaskKind
    source_url: str
    instructions: str
    provider_code: str | None = None
    expected_schema: str | None = None
    status: str
    result_text: str | None = None
    result_json: dict[str, Any] | None = None
    review_state: str = "not_reviewed"
    created_at: str
    updated_at: str


class BrowserAttempt(BaseModel):
    id: str
    task_id: str
    attempt_no: int = Field(ge=1)
    source: Literal["openclaw", "lab_ingest"]
    browser_profile: str
    started_at: str
    finished_at: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    outcome: str = "running"
    result_status: str | None = None
    validation_errors: list[str] = Field(default_factory=list)
    blocker: str | None = None
    result_hash: str | None = None
    created_at: str


class BrowserTaskIngestRequest(BaseModel):
    raw_text: str = Field(min_length=2, max_length=200_000)
    blocker: str | None = Field(default=None, max_length=500)


class FlightTripType(StrEnum):
    ROUND_TRIP = "round_trip"
    ONE_WAY = "one_way"


class CabinClass(StrEnum):
    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"
    FIRST = "first"


class FlightSearchRequest(BaseModel):
    case_id: str | None = None
    airline_codes: list[str] = Field(
        default_factory=lambda: ["CI", "BR", "CX", "JX", "AE", "IT", "EK", "NH"],
        min_length=1,
        max_length=12,
    )
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    depart_date: date
    return_date: date | None = None
    trip_type: FlightTripType = FlightTripType.ROUND_TRIP
    adults: int = Field(default=1, ge=1, le=20)
    children: int = Field(default=0, ge=0, le=20)
    infants: int = Field(default=0, ge=0, le=20)
    cabin: CabinClass = CabinClass.ECONOMY
    nonstop_preferred: bool = False
    max_total_twd: int | None = Field(default=None, ge=0)
    preferred_departure_window: str | None = Field(default=None, max_length=80)
    notes: str = Field(default="", max_length=1200)

    @field_validator("origin", "destination")
    @classmethod
    def normalize_iata(cls, value: str) -> str:
        value = value.strip().upper()
        if not value.isalpha() or len(value) != 3:
            raise ValueError("機場需使用 3 碼 IATA code，例如 TPE、NRT")
        return value

    @field_validator("airline_codes")
    @classmethod
    def normalize_airlines(cls, values: list[str]) -> list[str]:
        out: list[str] = []
        for value in values:
            code = value.strip().upper()
            if len(code) != 2 or not code.isalnum():
                raise ValueError(f"無效 airline code: {value}")
            if code not in out:
                out.append(code)
        return out

    @model_validator(mode="after")
    def validate_dates_and_party(self) -> "FlightSearchRequest":
        if self.origin == self.destination:
            raise ValueError("出發機場與目的地不可相同")
        if self.trip_type == FlightTripType.ROUND_TRIP:
            if self.return_date is None:
                raise ValueError("來回行程需要 return_date")
            if self.return_date < self.depart_date:
                raise ValueError("return_date 不可早於 depart_date")
        if self.trip_type == FlightTripType.ONE_WAY:
            self.return_date = None
        if self.infants > self.adults:
            raise ValueError("POC 安全規則：嬰兒人數不可多於成人，特殊情況請人工處理")
        return self

    @property
    def occupied_seats(self) -> int:
        # POC assumes infants are lap infants unless manually handled.
        return self.adults + self.children

    @property
    def party_total(self) -> int:
        return self.adults + self.children + self.infants


class FlightSearchRunStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class FlightSearchRun(BaseModel):
    id: str
    case_id: str | None = None
    request: FlightSearchRequest
    task_ids: list[str] = Field(default_factory=list)
    manual_handoffs: list[dict[str, Any]] = Field(default_factory=list)
    unsupported_airlines: list[str] = Field(default_factory=list)
    status: FlightSearchRunStatus = FlightSearchRunStatus.PLANNED
    selected_task_id: str | None = None
    selected_option_id: str | None = None
    created_at: str
    updated_at: str


class FlightSegment(BaseModel):
    flight_number: str = ""
    marketing_airline: str = ""
    operating_airline: str = ""
    origin: str
    destination: str
    departure_local: str = ""
    arrival_local: str = ""
    duration_minutes: int | None = Field(default=None, ge=0)


class FlightOption(BaseModel):
    option_id: str
    total_amount: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    fare_family: str = ""
    cabin: str = ""
    segments: list[FlightSegment] = Field(default_factory=list)
    stops: int = Field(default=0, ge=0)
    total_duration_minutes: int | None = Field(default=None, ge=0)
    checked_baggage: str = "unknown"
    carry_on: str = "unknown"
    change_rule_summary: str = "unknown"
    refund_rule_summary: str = "unknown"
    seat_selection: str = "unknown"
    warnings: list[str] = Field(default_factory=list)


class FlightSearchResultV1(BaseModel):
    schema_version: Literal["flight-search-v1"] = "flight-search-v1"
    airline_code: str
    airline_name: str
    source_url: str
    status: Literal["ok", "manual_required", "no_results", "blocked", "error"]
    observed_at: str
    currency: str | None = None
    options: list[FlightOption] = Field(default_factory=list)
    manual_handoff_reason: str | None = None
    notes: list[str] = Field(default_factory=list)

    @field_validator("airline_code")
    @classmethod
    def normalize_result_airline(cls, value: str) -> str:
        return value.upper()


class FlightRevalidationResultV1(BaseModel):
    schema_version: Literal["flight-revalidation-v1"] = "flight-revalidation-v1"
    airline_code: str
    airline_name: str
    source_url: str
    status: Literal["found", "unavailable", "manual_required", "blocked", "error"]
    observed_at: str
    original_option_id: str
    match_confidence: Literal["exact", "close", "uncertain"] = "uncertain"
    current_option: FlightOption | None = None
    differences: list[str] = Field(default_factory=list)
    manual_handoff_reason: str | None = None
    notes: list[str] = Field(default_factory=list)

    @field_validator("airline_code")
    @classmethod
    def normalize_result_airline(cls, value: str) -> str:
        return value.upper()


class FlightRevalidationCreateRequest(BaseModel):
    search_task_id: str
    option_id: str


class FlightRevalidationSummary(BaseModel):
    task_id: str
    search_task_id: str
    option_id: str
    status: str
    airline_code: str
    source_url: str
    observed_at: str | None = None
    match_confidence: str | None = None
    currency: str | None = None
    original_amount: float | None = None
    current_amount: float | None = None
    delta_amount: float | None = None
    delta_percent: float | None = None
    fare_family_changed: bool = False
    itinerary_changed: bool = False
    rules_changed: bool = False
    requires_human_acceptance: bool = False
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BookingChecklistItem(BaseModel):
    key: str
    label: str
    status: Literal["ok", "warning", "blocked"]
    detail: str


class BookingPreflightRequest(BaseModel):
    revalidation_task_id: str
    accept_price_change: bool = False


class BookingPreflightResult(BaseModel):
    schema_version: Literal["booking-preflight-v1"] = "booking-preflight-v1"
    ready: bool
    status: Literal["ready_for_human_checkout", "blocked", "needs_review"]
    case_id: str | None = None
    airline_code: str | None = None
    search_task_id: str | None = None
    revalidation_task_id: str
    option_id: str | None = None
    checked_at: str = Field(default_factory=now_iso)
    revalidation_age_minutes: float | None = None
    checklist: list[BookingChecklistItem] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_action: str
    human_confirmation_required: bool = True
    payment_handled_by_agent: bool = False


class StructuredFlightTaskPlan(BaseModel):
    run: FlightSearchRun | None = None
    tasks: list[BrowserTask] = Field(default_factory=list)
    manual_handoffs: list[dict[str, Any]] = Field(default_factory=list)
    unsupported_airlines: list[str] = Field(default_factory=list)


class BrowserTaskBatchRequest(BaseModel):
    task_ids: list[str] = Field(min_length=1, max_length=12)

    @field_validator("task_ids")
    @classmethod
    def unique_task_ids(cls, values: list[str]) -> list[str]:
        out: list[str] = []
        for value in values:
            value = value.strip()
            if value and value not in out:
                out.append(value)
        if not out:
            raise ValueError("task_ids 不可為空")
        return out


class FlightOptionSelectionRequest(BaseModel):
    task_id: str
    option_id: str


class HotelSiteTrustStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REVOKED = "revoked"


class HotelSiteGrantCreate(BaseModel):
    hotel_name: str = Field(min_length=1, max_length=160)
    official_url: str = Field(min_length=8, max_length=1000)
    trust_source: Literal["human", "registry", "google_hotels_official_link"] = "human"
    evidence_url: str | None = Field(default=None, max_length=1000)
    notes: str = Field(default="", max_length=1200)


class HotelSiteGrant(BaseModel):
    id: str
    hotel_name: str
    domain: str
    official_url: str
    trust_source: str
    evidence_url: str | None = None
    notes: str = ""
    status: HotelSiteTrustStatus = HotelSiteTrustStatus.APPROVED
    approved_at: str | None = None
    created_at: str
    updated_at: str


class HotelSearchRequest(BaseModel):
    case_id: str | None = None
    hotel_name: str = Field(min_length=1, max_length=160)
    official_url: str = Field(min_length=8, max_length=1000)
    checkin_date: date
    checkout_date: date
    rooms: int = Field(default=1, ge=1, le=8)
    adults: int = Field(default=2, ge=1, le=24)
    children_ages: list[int] = Field(default_factory=list, max_length=16)
    currency_preference: str = Field(default="TWD", min_length=3, max_length=3)
    max_total_twd: int | None = Field(default=None, ge=0)
    min_stars: int | None = Field(default=None, ge=1, le=5)
    breakfast_required: bool = False
    free_cancellation_preferred: bool = True
    notes: str = Field(default="", max_length=1200)

    @field_validator("currency_preference")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("currency_preference 必須是 3 碼貨幣代碼")
        return value

    @field_validator("children_ages")
    @classmethod
    def validate_child_ages(cls, values: list[int]) -> list[int]:
        if any(age < 0 or age > 17 for age in values):
            raise ValueError("children_ages 必須介於 0–17")
        return values

    @model_validator(mode="after")
    def validate_stay(self) -> "HotelSearchRequest":
        if self.checkout_date <= self.checkin_date:
            raise ValueError("checkout_date 必須晚於 checkin_date")
        if self.adults < self.rooms:
            raise ValueError("POC 規則：每間房至少需要一位成人")
        return self

    @property
    def nights(self) -> int:
        return (self.checkout_date - self.checkin_date).days


class HotelSearchRunStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class HotelSearchRun(BaseModel):
    id: str
    case_id: str | None = None
    request: HotelSearchRequest
    task_ids: list[str] = Field(default_factory=list)
    status: HotelSearchRunStatus = HotelSearchRunStatus.PLANNED
    selected_task_id: str | None = None
    selected_option_id: str | None = None
    created_at: str
    updated_at: str


class HotelRoomOption(BaseModel):
    option_id: str
    room_name: str = ""
    bed_type: str = "unknown"
    rate_name: str = ""
    occupancy_summary: str = ""
    total_amount: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    base_amount: float | None = Field(default=None, ge=0)
    taxes_and_fees: float | None = Field(default=None, ge=0)
    mandatory_property_fees: float | None = Field(default=None, ge=0)
    breakfast_included: bool | None = None
    refundable: bool | None = None
    cancellation_deadline_local: str | None = None
    payment_timing: Literal["pay_now", "pay_later", "pay_at_property", "unknown"] = "unknown"
    member_rate: bool = False
    loyalty_required: bool = False
    resort_fee_included: bool | None = None
    warnings: list[str] = Field(default_factory=list)


class HotelSearchResultV1(BaseModel):
    schema_version: Literal["hotel-search-v1"] = "hotel-search-v1"
    hotel_name: str
    source_url: str
    status: Literal["ok", "manual_required", "no_results", "blocked", "error"]
    observed_at: str
    checkin_date: date
    checkout_date: date
    rooms: int = Field(ge=1)
    adults: int = Field(ge=1)
    children_ages: list[int] = Field(default_factory=list)
    currency: str | None = None
    options: list[HotelRoomOption] = Field(default_factory=list)
    manual_handoff_reason: str | None = None
    notes: list[str] = Field(default_factory=list)


class HotelRevalidationResultV1(BaseModel):
    schema_version: Literal["hotel-revalidation-v1"] = "hotel-revalidation-v1"
    hotel_name: str
    source_url: str
    status: Literal["found", "unavailable", "manual_required", "blocked", "error"]
    observed_at: str
    original_option_id: str
    match_confidence: Literal["exact", "close", "uncertain"] = "uncertain"
    current_option: HotelRoomOption | None = None
    differences: list[str] = Field(default_factory=list)
    manual_handoff_reason: str | None = None
    notes: list[str] = Field(default_factory=list)


class HotelRevalidationCreateRequest(BaseModel):
    search_task_id: str
    option_id: str


class HotelRevalidationSummary(BaseModel):
    task_id: str
    search_task_id: str
    option_id: str
    status: str
    hotel_name: str
    source_url: str
    observed_at: str | None = None
    match_confidence: str | None = None
    currency: str | None = None
    original_amount: float | None = None
    current_amount: float | None = None
    delta_amount: float | None = None
    delta_percent: float | None = None
    room_changed: bool = False
    rate_changed: bool = False
    cancellation_changed: bool = False
    meal_changed: bool = False
    fees_changed: bool = False
    requires_human_acceptance: bool = False
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class HotelBookingPreflightRequest(BaseModel):
    revalidation_task_id: str
    accept_price_or_terms_change: bool = False


class HotelBookingPreflightResult(BaseModel):
    schema_version: Literal["hotel-booking-preflight-v1"] = "hotel-booking-preflight-v1"
    ready: bool
    status: Literal["ready_for_human_checkout", "blocked", "needs_review"]
    case_id: str | None = None
    hotel_name: str | None = None
    search_task_id: str | None = None
    revalidation_task_id: str
    option_id: str | None = None
    checked_at: str = Field(default_factory=now_iso)
    revalidation_age_minutes: float | None = None
    checklist: list[BookingChecklistItem] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_action: str
    human_confirmation_required: bool = True
    payment_handled_by_agent: bool = False


class StructuredHotelTaskPlan(BaseModel):
    run: HotelSearchRun
    task: BrowserTask



class ActionType(StrEnum):
    READ = "read"
    DRAFT = "draft"
    ACCEPT_PRICE_CHANGE = "accept_price_change"
    SEND_MESSAGE = "send_message"
    BOOK = "book"
    TICKET = "ticket"
    CANCEL = "cancel"
    REFUND = "refund"
    PAYMENT = "payment"


class ApprovalRequest(BaseModel):
    id: str
    case_id: str | None = None
    action_type: ActionType
    summary: str
    amount_twd: int | None = None
    status: str = "pending"
    created_at: str
    decided_at: str | None = None


class CustomerReplyRequest(BaseModel):
    case_id: str | None = None
    incoming_text: str = Field(min_length=1, max_length=8000)
    tone: str = "專業、親切、簡潔"


class AgentAskRequest(BaseModel):
    case_id: str | None = None
    message: str = Field(min_length=1, max_length=16000)
    session_user: str | None = None


class AgentReply(BaseModel):
    text: str
    source: str
    degraded: bool = False


class RadarItem(BaseModel):
    severity: str
    case_id: str
    title: str
    detail: str
    action: str


class Health(BaseModel):
    ok: bool
    openclaw_enabled: bool
    line_enabled: bool
    telegram_enabled: bool
    db_path: str
    app_version: str = "0.8.1"
    timestamp: str = Field(default_factory=now_iso)


class FontScale(StrEnum):
    NORMAL = "normal"
    LARGE = "large"
    XLARGE = "xlarge"


class UserPreferencesPatch(BaseModel):
    default_origin: str | None = Field(default=None, min_length=3, max_length=3)
    preferred_airlines: list[str] | None = None
    font_scale: FontScale | None = None
    simple_mode: bool | None = None
    onboarding_complete: bool | None = None

    @field_validator("default_origin")
    @classmethod
    def normalize_origin(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @field_validator("preferred_airlines")
    @classmethod
    def normalize_airlines(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        seen: list[str] = []
        for item in value:
            code = str(item).strip().upper()
            if code and code not in seen:
                seen.append(code)
        return seen[:12]


class UserPreferences(BaseModel):
    profile_id: str = "mom"
    default_origin: str = "TPE"
    preferred_airlines: list[str] = Field(default_factory=lambda: ["CI", "JX", "CX", "AE", "BR"])
    font_scale: FontScale = FontScale.LARGE
    simple_mode: bool = True
    onboarding_complete: bool = False
    updated_at: str = Field(default_factory=now_iso)


class MomIntentRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    case_id: str | None = None


class MomIntentSuggestion(BaseModel):
    action: Literal["customer_reply", "flight_search", "hotel_search", "itinerary", "visa", "new_case", "case_lookup", "unknown"]
    label: str
    reason: str
    confidence: float = Field(ge=0, le=1)


class MomIntentResponse(BaseModel):
    text: str
    suggestions: list[MomIntentSuggestion]


class SkillFeedbackType(StrEnum):
    ACCEPTED = "accepted"
    EDITED = "edited"
    PREFER_FUTURE = "prefer_future"
    REJECTED = "rejected"


class SkillFeedbackCreate(BaseModel):
    skill_key: str = Field(min_length=1, max_length=80)
    feedback_type: SkillFeedbackType
    case_id: str | None = None
    source: str = Field(default="mom-ui", max_length=40)
    draft_text: str | None = Field(default=None, max_length=16000)
    final_text: str | None = Field(default=None, max_length=16000)
    note: str | None = Field(default=None, max_length=2000)


class SkillFeedbackRecord(BaseModel):
    id: str
    skill_key: str
    feedback_type: SkillFeedbackType
    case_id: str | None = None
    source: str
    draft_redacted: str | None = None
    final_redacted: str | None = None
    note_redacted: str | None = None
    skill_hash: str | None = None
    edit_ratio: float | None = None
    possible_pii: bool = False
    created_at: str


class SkillFeedbackSummary(BaseModel):
    schema_version: Literal["skill-feedback-summary-v1"] = "skill-feedback-summary-v1"
    skill_key: str | None = None
    total: int
    accepted: int
    edited: int
    prefer_future: int
    rejected: int
    average_edit_ratio: float | None = None
    ready_for_proposal: bool = False
    proposal_reason: str
