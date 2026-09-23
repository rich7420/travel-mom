from __future__ import annotations
import hmac
from fastapi import Request
from app.config import settings

def is_production() -> bool:
    return settings.app_env.strip().lower() in {"prod","production"}

def validate_runtime_settings() -> None:
    if is_production() and not settings.admin_token:
        raise RuntimeError("TRAVEL_DESK_ADMIN_TOKEN is required when APP_ENV=production")
    if settings.max_request_body_bytes < 16_384:
        raise RuntimeError("MAX_REQUEST_BODY_BYTES is unreasonably small")

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
    return bool(supplied) and hmac.compare_digest(supplied,expected)

_BASE={"X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer","Permissions-Policy":"camera=(), microphone=(), geolocation=()","X-Frame-Options":"DENY"}
_STRICT=("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
_LEGACY=("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")

def security_headers_for_path(path: str) -> dict[str,str]:
    headers=dict(_BASE); headers["Content-Security-Policy"]=_LEGACY if path=="/admin" or path.startswith("/admin-static/") else _STRICT; return headers

SECURITY_HEADERS={**_BASE,"Content-Security-Policy":_STRICT}
