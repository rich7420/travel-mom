from __future__ import annotations

from app.providers.base import FlightOption, HotelOption, TravelProvider


class DemoProvider(TravelProvider):
    def flights(self, origin: str, destination: str, adults: int = 1) -> list[FlightOption]:
        rows = [
            ("Demo Air A", "DA101", "08:30", "12:05", 215, 0, 13900, "23kg", "fee + fare difference"),
            ("Demo Air B", "DB221", "06:10", "10:00", 230, 0, 12400, "20kg", "non-refundable; change fee"),
            ("Demo Air C", "DC887", "10:40", "16:20", 340, 1, 10800, "15kg", "restricted"),
        ]
        return [
            FlightOption(provider="demo", airline=a, flight_no=f, depart=d, arrive=ar, duration_min=mins, stops=s,
                         total_twd=price*adults, baggage=bag, change_rule=rule,
                         source_url="https://example.invalid/demo-airline", customer_safe=False)
            for a,f,d,ar,mins,s,price,bag,rule in rows
        ]

    def hotels(self, destination: str, nights: int = 2) -> list[HotelOption]:
        rows = [
            ("Demo Central Hotel", 3900, 650, 0, 4.5, 2, True, "Free cancellation until 3 days before"),
            ("Demo Value Hotel", 3100, 500, 300, 4.0, 8, False, "Non-refundable"),
            ("Demo Flexible Suites", 4300, 700, 0, 4.5, 5, True, "Free cancellation until 1 day before"),
        ]
        out = []
        for name, nightly, taxes, fees, stars, station, breakfast, cancel in rows:
            total = nightly*nights + taxes + fees
            out.append(HotelOption(provider="demo", name=name, nightly_twd=nightly, nights=nights, taxes_twd=taxes,
                                   fees_twd=fees, total_twd=total, stars=stars, station_minutes=station,
                                   breakfast=breakfast, cancellation=cancel,
                                   source_url="https://example.invalid/demo-hotel", customer_safe=False))
        return out


demo_provider = DemoProvider()
