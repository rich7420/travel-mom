from __future__ import annotations

from abc import ABC, abstractmethod
from pydantic import BaseModel


class FlightOption(BaseModel):
    provider: str
    airline: str
    flight_no: str
    depart: str
    arrive: str
    duration_min: int
    stops: int
    total_twd: int
    baggage: str
    change_rule: str
    source_url: str
    customer_safe: bool = False


class HotelOption(BaseModel):
    provider: str
    name: str
    nightly_twd: int
    nights: int
    taxes_twd: int
    fees_twd: int
    total_twd: int
    stars: float
    station_minutes: int
    breakfast: bool
    cancellation: str
    source_url: str
    customer_safe: bool = False


class TravelProvider(ABC):
    @abstractmethod
    def flights(self, origin: str, destination: str, adults: int = 1) -> list[FlightOption]: ...

    @abstractmethod
    def hotels(self, destination: str, nights: int = 2) -> list[HotelOption]: ...
