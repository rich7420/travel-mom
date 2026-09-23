from __future__ import annotations

from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse

from app.airlines import all_airlines
from app.hotels import all_networks
from app.config import settings


ROOT = Path(__file__).resolve().parents[2]


def _check(key: str, label: str, status: str, detail: str, scope: str) -> dict[str, str]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "detail": detail,
        "scope": scope,
    }


def _is_private_gateway_host(base_url: str) -> bool:
    host = (urlparse(base_url).hostname or "").lower()
    if host in {"localhost", "host.docker.internal"}:
        return True
    try:
        address = ip_address(host)
    except ValueError:
        return host.endswith(".internal") or host.endswith(".local")
    return address.is_loopback or address.is_private


def build_system_readiness() -> dict:
    """Configuration readiness only; it does not claim live site connectivity."""

    checks: list[dict[str, str]] = []

    db_parent = Path(settings.db_path).expanduser().resolve().parent
    checks.append(
        _check(
            "database",
            "案件資料庫",
            "ok" if db_parent.exists() else "blocked",
            f"SQLite 路徑：{settings.db_path}",
            "core",
        )
    )

    airlines = all_airlines()
    checks.append(
        _check(
            "airline_registry",
            "航空公司 Registry",
            "ok" if len(airlines) >= 6 else "blocked",
            f"已載入 {len(airlines)} 家：{', '.join(a.code for a in airlines)}",
            "core",
        )
    )

    recipes = sorted((ROOT / "recipes" / "airlines").glob("*.json"))
    checks.append(
        _check(
            "airline_recipes",
            "航空官網 Recipes",
            "ok" if len(recipes) >= 8 else "blocked",
            f"已找到 {len(recipes)} 份 airline semantic recipes",
            "core",
        )
    )

    hotel_networks = all_networks()
    checks.append(
        _check(
            "hotel_registry",
            "飯店官網 Registry",
            "ok" if len(hotel_networks) >= 6 else "warning",
            f"已載入 {len(hotel_networks)} 個 built-in hotel networks：{', '.join(h.code for h in hotel_networks)}",
            "core",
        )
    )
    hotel_recipe = ROOT / "recipes" / "official_hotel_search.json"
    checks.append(
        _check(
            "hotel_recipe",
            "飯店官網 Semantic Recipe",
            "ok" if hotel_recipe.exists() else "blocked",
            str(hotel_recipe.relative_to(ROOT)) if hotel_recipe.exists() else "缺少 official_hotel_search.json",
            "core",
        )
    )

    skills = sorted((ROOT / "openclaw" / "skills").glob("*/SKILL.md"))
    checks.append(
        _check(
            "workspace_skills",
            "OpenClaw Workspace Skills",
            "ok" if len(skills) >= 19 else "warning",
            f"已找到 {len(skills)} 個本地 skills",
            "core",
        )
    )

    if settings.openclaw_enabled:
        missing = []
        if not settings.openclaw_gateway_token:
            missing.append("Gateway token")
        if not settings.openclaw_base_url:
            missing.append("Gateway URL")
        if not settings.openclaw_browser_model:
            missing.append("browser model")
        checks.append(
            _check(
                "openclaw_gateway",
                "OpenClaw Gateway",
                "blocked" if missing else "ok",
                "缺少：" + "、".join(missing) if missing else f"已設定 {settings.openclaw_base_url}",
                "browser_lab",
            )
        )
        checks.append(
            _check(
                "gateway_network",
                "Gateway 網路邊界",
                "ok" if _is_private_gateway_host(settings.openclaw_base_url) else "blocked",
                "位於 loopback/private host" if _is_private_gateway_host(settings.openclaw_base_url) else "Gateway 看起來位於公開 host；operator token 不應公開",
                "browser_lab",
            )
        )
    else:
        checks.append(
            _check(
                "openclaw_gateway",
                "OpenClaw Gateway",
                "warning",
                "目前停用；離線 POC 可用，但不能執行真實 Browser Lab",
                "browser_lab",
            )
        )

    checks.append(
        _check(
            "agent_separation",
            "對話與瀏覽 Agent 隔離",
            "ok" if settings.openclaw_model != settings.openclaw_browser_model else "blocked",
            f"chat={settings.openclaw_model}；browser={settings.openclaw_browser_model}",
            "browser_lab",
        )
    )
    checks.append(
        _check(
            "browser_profile",
            "Browser Profile",
            "ok" if settings.openclaw_browser_profile == "openclaw" else "warning",
            "使用隔離 openclaw profile" if settings.openclaw_browser_profile == "openclaw" else f"目前使用 {settings.openclaw_browser_profile}；可能包含登入狀態，需人工確認",
            "browser_lab",
        )
    )

    if settings.line_enabled:
        missing = []
        if not settings.line_channel_access_token:
            missing.append("access token")
        if not settings.line_channel_secret:
            missing.append("channel secret")
        if not settings.line_allowed_user_ids:
            missing.append("allowlist user ID")
        checks.append(
            _check(
                "line_channel",
                "媽媽 LINE 入口",
                "blocked" if missing else "ok",
                "缺少：" + "、".join(missing) if missing else f"已 allowlist {len(settings.line_allowed_user_ids)} 位使用者",
                "mom_pilot",
            )
        )
    else:
        checks.append(
            _check(
                "line_channel",
                "媽媽 LINE 入口",
                "warning",
                "尚未啟用；可先用 Web UI 測試",
                "mom_pilot",
            )
        )

    if settings.telegram_enabled:
        missing = []
        if not settings.telegram_bot_token:
            missing.append("bot token")
        if not settings.telegram_webhook_secret:
            missing.append("webhook secret")
        if not settings.telegram_allowed_chat_ids:
            missing.append("allowed chat ID")
        checks.append(
            _check(
                "telegram_channel",
                "Telegram 備援入口",
                "blocked" if missing else "ok",
                "缺少：" + "、".join(missing) if missing else "已設定管理/備援 allowlist",
                "optional",
            )
        )
    else:
        checks.append(_check("telegram_channel", "Telegram 備援入口", "warning", "未啟用（非必要）", "optional"))

    checks.append(
        _check(
            "pii_encryption",
            "PII Vault 金鑰",
            "ok" if settings.pii_fernet_key else "warning",
            "已設定 Fernet key" if settings.pii_fernet_key else "尚未設定；不可放入真實護照/生日等敏感資料",
            "mom_pilot",
        )
    )

    by_scope: dict[str, dict[str, int]] = {}
    for check in checks:
        scope = check["scope"]
        by_scope.setdefault(scope, {"ok": 0, "warning": 0, "blocked": 0})
        by_scope[scope][check["status"]] += 1

    core_blocked = any(c["scope"] == "core" and c["status"] == "blocked" for c in checks)
    browser_blocked = any(c["scope"] == "browser_lab" and c["status"] == "blocked" for c in checks)
    mom_blocked = any(c["scope"] == "mom_pilot" and c["status"] == "blocked" for c in checks)

    return {
        "schema_version": "configuration-readiness-v2",
        "offline_poc_ready": not core_blocked,
        "live_browser_lab_configured": settings.openclaw_enabled and not core_blocked and not browser_blocked,
        "mom_line_pilot_configured": settings.line_enabled and not core_blocked and not browser_blocked and not mom_blocked,
        "checks": checks,
        "summary": by_scope,
        "disclaimer": "這只檢查設定與本地資產，不代表航空/飯店官網、OpenClaw Gateway 或 LINE webhook 已完成實機連線測試。",
    }
