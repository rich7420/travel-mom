from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class HotelNetworkDefinition:
    code: str
    name: str
    official_home: str
    allowed_domains: tuple[str, ...]
    notes: tuple[str, ...] = ()
    evidence_urls: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["allowed_domains"] = list(self.allowed_domains)
        data["notes"] = list(self.notes)
        data["evidence_urls"] = list(self.evidence_urls)
        return data


# Registry entries are conveniences, not a complete hotel universe. Independent properties
# are approved through HotelSiteGrant instead of weakening the global browser allowlist.
HOTEL_NETWORKS: dict[str, HotelNetworkDefinition] = {
    "MARRIOTT": HotelNetworkDefinition(
        code="MARRIOTT",
        name="Marriott Bonvoy",
        official_home="https://www.marriott.com/",
        allowed_domains=("marriott.com",),
        notes=("Direct Marriott reservations can carry member/direct-booking benefits.",),
        evidence_urls=("https://www.marriott.com/online-hotel-booking.mi",),
    ),
    "HILTON": HotelNetworkDefinition(
        code="HILTON",
        name="Hilton",
        official_home="https://www.hilton.com/",
        allowed_domains=("hilton.com",),
        notes=("Official site supports direct booking and reservation management.",),
        evidence_urls=("https://www.hilton.com/en/",),
    ),
    "HYATT": HotelNetworkDefinition(
        code="HYATT",
        name="Hyatt",
        official_home="https://www.hyatt.com/",
        allowed_domains=("hyatt.com",),
        notes=("Official search supports dates, rooms/guests and special-rate selectors.",),
        evidence_urls=("https://www.hyatt.com/",),
    ),
    "IHG": HotelNetworkDefinition(
        code="IHG",
        name="IHG Hotels & Resorts",
        official_home="https://www.ihg.com/",
        allowed_domains=("ihg.com",),
    ),
    "ACCOR": HotelNetworkDefinition(
        code="ACCOR",
        name="ALL - Accor",
        official_home="https://all.accor.com/",
        allowed_domains=("all.accor.com", "accor.com"),
    ),
    "SHANGRILA": HotelNetworkDefinition(
        code="SHANGRILA",
        name="Shangri-La",
        official_home="https://www.shangri-la.com/",
        allowed_domains=("shangri-la.com",),
    ),
}


def host_matches_domain(host: str, domain: str) -> bool:
    host = host.lower().strip(".")
    domain = domain.lower().strip(".")
    return host == domain or host.endswith("." + domain)


def normalize_domain(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("hotel official_url 必須是 https URL")
    return parsed.hostname.lower().strip(".")


def network_for_url(url: str) -> HotelNetworkDefinition | None:
    try:
        host = normalize_domain(url)
    except ValueError:
        return None
    for network in HOTEL_NETWORKS.values():
        if any(host_matches_domain(host, d) for d in network.allowed_domains):
            return network
    return None


def all_networks() -> list[HotelNetworkDefinition]:
    return list(HOTEL_NETWORKS.values())


def all_network_domains() -> set[str]:
    out: set[str] = set()
    for network in HOTEL_NETWORKS.values():
        out.update(d.lower() for d in network.allowed_domains)
    return out
