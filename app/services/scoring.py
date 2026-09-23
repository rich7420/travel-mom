from __future__ import annotations

from app.providers.base import FlightOption, HotelOption


def flight_score(x: FlightOption) -> tuple[float, list[str]]:
    score = 100.0
    reasons: list[str] = []
    score -= x.total_twd / 1000 * 1.25
    score -= x.duration_min / 60 * 2.2
    score -= x.stops * 14
    if x.stops == 0:
        reasons.append("直飛")
        score += 5
    if "23kg" in x.baggage or "20kg" in x.baggage:
        reasons.append("含託運行李")
        score += 3
    hour = int(x.depart.split(":")[0])
    if 7 <= hour <= 11:
        reasons.append("出發時間友善")
        score += 3
    if "non-refundable" not in x.change_rule.lower():
        reasons.append("改票彈性較好")
        score += 2
    return round(score, 2), reasons


def rank_flights(options: list[FlightOption]) -> list[dict]:
    ranked = []
    for x in options:
        score, reasons = flight_score(x)
        ranked.append({"option": x.model_dump(), "score": score, "reasons": reasons})
    return sorted(ranked, key=lambda r: r["score"], reverse=True)


def hotel_score(x: HotelOption) -> tuple[float, list[str]]:
    score = 100.0
    reasons: list[str] = []
    score -= x.total_twd / 1000 * 1.6
    score -= x.station_minutes * 0.9
    score += x.stars * 3
    if x.station_minutes <= 5:
        reasons.append("離車站很近")
        score += 5
    if x.breakfast:
        reasons.append("含早餐")
        score += 2
    if "free cancellation" in x.cancellation.lower():
        reasons.append("可免費取消")
        score += 5
    return round(score, 2), reasons


def rank_hotels(options: list[HotelOption]) -> list[dict]:
    ranked = []
    for x in options:
        score, reasons = hotel_score(x)
        ranked.append({"option": x.model_dump(), "score": score, "reasons": reasons})
    return sorted(ranked, key=lambda r: r["score"], reverse=True)
