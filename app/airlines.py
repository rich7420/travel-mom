from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import json


@dataclass(frozen=True)
class AirlineDefinition:
    code: str
    name_zh: str
    name_en: str
    official_home: str
    booking_url: str
    allowed_domains: tuple[str, ...]
    direct_online_max_occupied: int | None = None
    direct_online_max_total: int | None = None
    notes: tuple[str, ...] = ()
    source_note: str = ""
    evidence_urls: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["allowed_domains"] = list(self.allowed_domains)
        data["notes"] = list(self.notes)
        data["evidence_urls"] = list(self.evidence_urls)
        return data


AIRLINES: dict[str, AirlineDefinition] = {
    "CI": AirlineDefinition(
        code="CI",
        name_zh="中華航空",
        name_en="China Airlines",
        official_home="https://www.china-airlines.com/tw/zh",
        booking_url="https://www.china-airlines.com/tw/zh/booking/book-flights/flight-search",
        allowed_domains=("china-airlines.com", "booking.china-airlines.com", "flights.china-airlines.com"),
        notes=("POC 不硬編碼官網旅客上限；若網站拒絕則轉人工。",),
        source_note="China Airlines official booking/homepage reviewed 2026-08.",
        evidence_urls=("https://www.china-airlines.com/tw/en", "https://www.china-airlines.com/tw/en/booking/book-flights/flight-search"),
    ),
    "BR": AirlineDefinition(
        code="BR",
        name_zh="長榮航空",
        name_en="EVA Air",
        official_home="https://www.evaair.com/zh-tw/",
        booking_url="https://booking.evaair.com/flyeva/eva/b2c/booking-online.aspx?lang=zh-tw",
        allowed_domains=("evaair.com", "booking.evaair.com", "flights.evaair.com"),
        direct_online_max_occupied=9,
        notes=(
            "官網每次交易最多 9 張佔位機票（不含嬰兒），且至少一位 16 歲以上成人同行。",
            "官網明示選完航班票價後仍需再次確認總價。",
        ),
        source_note="EVA Air official online booking reviewed 2026-08.",
        evidence_urls=(
            "https://www.evaair.com/zh-tw/plan-and-book/book-online/",
            "https://booking.evaair.com/flyeva/eva/b2c/booking-online.aspx?lang=zh-tw",
        ),
    ),
    "CX": AirlineDefinition(
        code="CX",
        name_zh="國泰航空",
        name_en="Cathay Pacific",
        official_home="https://www.cathaypacific.com/cx/zh_TW.html",
        booking_url="https://www.cathaypacific.com/cx/en_TW/book-a-trip.html",
        allowed_domains=("cathaypacific.com",),
        direct_online_max_total=9,
        notes=("官網明示超過 9 位旅客無法線上訂位，需聯絡訂位辦公室。",),
        source_note="Cathay Pacific official Book a trip page reviewed 2026-08.",
        evidence_urls=("https://www.cathaypacific.com/cx/en_TW/book-a-trip.html",),
    ),
    "JX": AirlineDefinition(
        code="JX",
        name_zh="星宇航空",
        name_en="STARLUX Airlines",
        official_home="https://www.starlux-airlines.com/zh-TW",
        booking_url="https://www.starlux-airlines.com/flights/en-tw/",
        allowed_domains=("starlux-airlines.com",),
        notes=("官網公開促銷/搜尋票價可能是過去 48 小時蒐集值，正式報價前一定重驗。",),
        source_note="STARLUX official flight search reviewed 2026-08.",
        evidence_urls=("https://www.starlux-airlines.com/flights/en-tw/",),
    ),
    "AE": AirlineDefinition(
        code="AE",
        name_zh="華信航空",
        name_en="Mandarin Airlines",
        official_home="https://www.mandarin-airlines.com/",
        booking_url="https://www.mandarin-airlines.com/b2c/BookingNPurchase",
        allowed_domains=("mandarin-airlines.com",),
        direct_online_max_occupied=4,
        notes=(
            "官網/APP/便利商店直接訂位每筆最多 4 位（嬰兒除外）。",
            "官網另有「訂位延遲付款」流程；POC 只搜尋/預填，不自動付款。",
        ),
        source_note="Mandarin Airlines official FAQ reviewed 2026-08.",
        evidence_urls=("https://www.mandarin-airlines.com/Content/FAQ-2017020008-80", "https://www.mandarin-airlines.com/b2c/BookingNPurchase", "https://www.mandarin-airlines.com/b2c/bookingpaylater"),
    ),
    "IT": AirlineDefinition(
        code="IT",
        name_zh="台灣虎航",
        name_en="Tigerair Taiwan",
        official_home="https://www.tigerairtw.com/",
        booking_url="https://booking.tigerairtw.com/",
        allowed_domains=("tigerairtw.com", "booking.tigerairtw.com"),
        notes=(
            "官網訂位系統可能出現 Waiting Room；把排隊/限時結帳視為 manual blocker，不嘗試繞過。",
            "搜尋結果與 checkout 有時效，付款前一定重新驗價。",
        ),
        source_note="Tigerair Taiwan official booking engine reviewed 2026-08.",
        evidence_urls=("https://booking.tigerairtw.com/", "https://www.tigerairtw.com/"),
    ),
    "EK": AirlineDefinition(
        code="EK",
        name_zh="阿聯酋航空",
        name_en="Emirates",
        official_home="https://www.emirates.com/tw/chinese/",
        booking_url="https://www.emirates.com/tw/chinese/book/",
        allowed_domains=("emirates.com",),
        direct_online_max_total=9,
        notes=("官網明示每筆最多 9 位，包含成人、兒童與嬰兒。",),
        source_note="Emirates official Taiwan booking page reviewed 2026-08.",
        evidence_urls=("https://www.emirates.com/tw/chinese/book/",),
    ),
    "NH": AirlineDefinition(
        code="NH",
        name_zh="全日空",
        name_en="ANA",
        official_home="https://www.ana.co.jp/zh/tw/",
        booking_url="https://www.ana.co.jp/zh/tw/plan-book/",
        allowed_domains=("ana.co.jp",),
        notes=(
            "ANA 日本國內線官方頁明示最多 9 位成人；國際線 POC 不把此數字硬套用，實際以當下國際訂位 UI 為準。",
            "嬰兒需獨立座位、無人陪伴兒童或特殊協助等情況直接轉人工。",
        ),
        source_note="ANA official reservation/support pages reviewed 2026-08.",
        evidence_urls=("https://www.ana.co.jp/zh/tw/plan-book/", "https://www.ana.co.jp/en/jp/guide/reservation/domestic/online/"),
    ),
}


RECIPE_ROOT = Path(__file__).resolve().parents[1] / "recipes" / "airlines"


def get_airline(code: str) -> AirlineDefinition | None:
    return AIRLINES.get(code.strip().upper())


def all_airlines() -> list[AirlineDefinition]:
    return [AIRLINES[k] for k in ("CI", "BR", "CX", "JX", "AE", "IT", "EK", "NH")]


def all_official_domains() -> set[str]:
    domains: set[str] = set()
    for airline in AIRLINES.values():
        domains.update(d.lower() for d in airline.allowed_domains)
    return domains


def host_matches_domain(host: str, domain: str) -> bool:
    host = host.lower().strip(".")
    domain = domain.lower().strip(".")
    return host == domain or host.endswith("." + domain)


def official_airline_for_url(url: str) -> AirlineDefinition | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").lower()
    for airline in AIRLINES.values():
        if any(host_matches_domain(host, domain) for domain in airline.allowed_domains):
            return airline
    return None


def load_airline_recipe(code: str) -> dict[str, Any]:
    path = RECIPE_ROOT / f"{code.upper()}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
