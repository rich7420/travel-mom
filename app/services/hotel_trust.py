from __future__ import annotations

from app.hotels import all_network_domains, host_matches_domain, network_for_url, normalize_domain
from app.models import HotelSiteGrant, HotelSiteGrantCreate
from app.repositories import hotel_site_grant_repo

KNOWN_NON_OFFICIAL_BOOKING_DOMAINS = {
    "booking.com",
    "agoda.com",
    "expedia.com",
    "hotels.com",
    "trip.com",
    "traveloka.com",
    "tripadvisor.com",
    "trivago.com",
    "kayak.com",
    "priceline.com",
    "hotelscombined.com",
    "klook.com",
    "kkday.com",
    "rakuten.com",
    "jalan.net",
    "ctrip.com",
    "google.com",
}


def _is_known_third_party(domain: str) -> bool:
    return any(host_matches_domain(domain, d) for d in KNOWN_NON_OFFICIAL_BOOKING_DOMAINS)


def hotel_allowed_domains(url: str) -> tuple[str, ...]:
    network = network_for_url(url)
    if network:
        return network.allowed_domains
    try:
        domain = normalize_domain(url)
    except ValueError:
        return ()
    grant = hotel_site_grant_repo.get_by_domain(domain)
    if grant:
        return (grant.domain,)
    return ()


def is_trusted_hotel_url(url: str) -> bool:
    return bool(hotel_allowed_domains(url))


def approve_independent_hotel_site(data: HotelSiteGrantCreate) -> HotelSiteGrant:
    domain = normalize_domain(data.official_url)
    if _is_known_third_party(domain):
        raise ValueError("這個 domain 看起來是 OTA/搜尋平台，不可登記成飯店 official site")
    if network_for_url(data.official_url):
        # Built-in networks are already trusted and should not create duplicate grants.
        raise ValueError("此網址屬於內建可信飯店集團 registry，不需要額外 attestation")
    if data.trust_source != "human":
        raise ValueError("獨立飯店 official domain 的核准必須由 human 明確確認")
    return hotel_site_grant_repo.create(data, domain=domain, approved=True)


def builtin_hotel_domains() -> list[str]:
    return sorted(all_network_domains())
