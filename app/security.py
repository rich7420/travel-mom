from __future__ import annotations
import hmac
import re
from urllib.parse import urlsplit
from fastapi import HTTPException, Request
from app.config import settings

def is_production() -> bool:
    return settings.app_env.strip().lower() in {"prod","production"}

def validate_runtime_settings() -> None:
    if settings.auth_mode not in {"token", "cloudflare"}:
        raise RuntimeError("AUTH_MODE must be token or cloudflare")
    if settings.auth_mode == "cloudflare":
        if not re.fullmatch(r"https://[a-z0-9-]+\.cloudflareaccess\.com", settings.cloudflare_access_issuer):
            raise RuntimeError("CLOUDFLARE_ACCESS_ISSUER must be an HTTPS Cloudflare team domain")
        if not settings.cloudflare_access_audience or not settings.cloudflare_access_emails or not settings.cloudflare_access_admin_emails:
            raise RuntimeError("Cloudflare Access requires audience and explicit operator/admin email lists")
        if any("*" in email or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) for email in (*settings.cloudflare_access_emails, *settings.cloudflare_access_admin_emails)):
            raise RuntimeError("Cloudflare Access allowlists must contain complete email addresses")
        url = urlsplit(settings.public_base_url)
        try:
            url.port
        except ValueError:
            raise RuntimeError("PUBLIC_BASE_URL has an invalid port") from None
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment:
            raise RuntimeError("PUBLIC_BASE_URL must be the HTTPS application origin")
    if is_production() and settings.auth_mode == "token" and not settings.admin_token:
        raise RuntimeError("TRAVEL_DESK_ADMIN_TOKEN is required when APP_ENV=production")
    if settings.max_request_body_bytes < 16_384:
        raise RuntimeError("MAX_REQUEST_BODY_BYTES is unreasonably small")
    if settings.quote_max_age_hours <= 0:
        raise RuntimeError("QUOTE_MAX_AGE_HOURS must be positive")

def presented_admin_token(request: Request) -> str:
    direct=request.headers.get("x-travel-desk-admin-token","").strip()
    if direct: return direct
    authorization=request.headers.get("authorization",""); scheme,_,value=authorization.partition(" ")
    return value.strip() if scheme.lower()=="bearer" else ""

def requires_operator_auth(path: str) -> bool:
    return path=="/api" or path.startswith("/api/")

def operator_authorized(request: Request) -> bool:
    if not requires_operator_auth(request.url.path): return True
    expected=settings.admin_token
    if not expected: return not is_production()
    supplied=presented_admin_token(request)
    return bool(supplied) and hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))

# Exact exemptions only. Channel handlers authenticate their own signed payloads.
_ACCESS_EXEMPT = {("GET", "/livez"), ("POST", "/webhooks/line"), ("POST", "/webhooks/telegram")}
_OPERATOR_ROUTES = (
    ("GET", r"/api/(?:auth/session|airlines|hotels/networks|cases(?:/[^/]+)?)"),
    ("POST", r"/api/(?:cases|customer-reply|browser/(?:flight-search|hotel-search))"),
    ("PATCH", r"/api/cases/[^/]+"),
    ("GET", r"/api/browser/(?:runs|hotel-runs)(?:/[^/]+)?"),
    ("GET", r"/api/guided/[^/]+/resume"),
    ("POST", r"/api/guided/[^/]+/(?:start|back|save|reset|reply)"),
    ("GET", r"/api/mom/cases/[^/]+/(?:travel-files|attachment-receipts/[^/]+|travellers/[^/]+/reveal|attachments/[^/]+/download)"),
    ("POST", r"/api/mom/cases/[^/]+/(?:travellers|roster/verify|work-handover|travellers/[^/]+/archive|attachments/[^/]+/archive|documents/[^/]+/attachments|work-items/[^/]+/acknowledge)"),
    ("PATCH", r"/api/mom/cases/[^/]+/travellers/[^/]+"),
    ("GET", r"/api/mom/work-items"),
    ("GET", r"/api/mom/cases/[^/]+/operations"),
    ("GET", r"/api/mom/cases/[^/]+/(?:quotes|pretrip)/[^/]+/document"),
    ("POST", r"/api/mom/cases/[^/]+/(?:quotes|work-items|bookings|documents|ledger|pretrip)"),
    ("POST", r"/api/mom/cases/[^/]+/lifecycle/(?:close|reopen)"),
    ("POST", r"/api/mom/cases/[^/]+/quotes/[^/]+/(?:sent|accept|reject)"),
    ("POST", r"/api/mom/cases/[^/]+/(?:bookings|ledger)/[^/]+/void"),
    ("POST", r"/api/mom/cases/[^/]+/bookings/[^/]+/rebind"),
    ("POST", r"/api/mom/cases/[^/]+/pretrip/[^/]+/deliver"),
    ("PATCH", r"/api/mom/cases/[^/]+/(?:work-items|documents)/[^/]+"),
    ("GET", r"/api/mom/(?:home|preferences|cases/[^/]+(?:/options)?|search-progress/(?:flight|hotel)/[^/]+)"),
    ("PATCH", r"/api/mom/preferences"),
    ("POST", r"/api/mom/(?:intent|skill-feedback|cases/[^/]+/(?:options|selection)|(?:flight|hotel)-search/[^/]+/start)"),
    ("DELETE", r"/api/mom/cases/[^/]+/selection/(?:flight|hotel)"),
)


def access_exempt(request: Request) -> bool:
    return (request.method, request.url.path) in _ACCESS_EXEMPT


def access_requires_admin(request: Request) -> bool:
    path = request.url.path
    if path == "/api" or path.startswith("/api/"):
        return not any(request.method == method and re.fullmatch(pattern, path) for method, pattern in _OPERATOR_ROUTES)
    return not (request.method in {"GET", "HEAD"} and (path in {"/", "/health"} or path.startswith("/static/")))


def verify_access_origin(request: Request) -> None:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        url = urlsplit(settings.public_base_url)
        host = f"[{url.hostname}]" if ":" in url.hostname else url.hostname
        port = f":{url.port}" if url.port not in {None, 443} else ""
        expected = f"https://{host}{port}"
        if request.headers.get("origin") != expected:
            raise HTTPException(403, "request origin not allowed")

_BASE={"X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer","Permissions-Policy":"camera=(), microphone=(), geolocation=()","X-Frame-Options":"DENY"}
_STRICT=("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
_LEGACY=("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")

def security_headers_for_path(path: str) -> dict[str,str]:
    headers=dict(_BASE); headers["Content-Security-Policy"]=_LEGACY if path=="/admin" or path.startswith("/admin-static/") else _STRICT; return headers

SECURITY_HEADERS={**_BASE,"Content-Security-Policy":_STRICT}
