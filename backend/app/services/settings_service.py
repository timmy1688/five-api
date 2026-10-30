"""系统设置。推理审计以这里的开关为准，单个 Key 仍可单独打开。

网关运行参数存在 system_settings。没有记录时用环境变量里的默认值。
"""

import secrets
import time

from tortoise.exceptions import IntegrityError

from app.config import settings
from app.models import SystemSetting

INFERENCE_AUDIT_KEY = "inference_audit_enabled"
KEYWORD_FILTER_KEY = "keyword_filter_enabled"
SECRET_SCAN_KEY = "secret_scan_enabled"
AI_AUDIT_KEY = "ai_audit"
GATEWAY_KEY = "gateway"
METRICS_TOKEN_KEY = "metrics_token"
_CACHE_TTL = 2.0
_cache: tuple[float, bool] | None = None
_secret_cache: tuple[float, bool] | None = None
_ai_cache: tuple[float, dict] | None = None
_gateway_cache: tuple[float, dict] | None = None

async def metrics_token() -> str:
    """Bearer token for scraping /metrics remotely, created on first use."""
    row = await SystemSetting.get_or_none(key=METRICS_TOKEN_KEY)
    if row is not None:
        return row.value["token"]
    token = secrets.token_urlsafe(32)
    try:
        await SystemSetting.create(key=METRICS_TOKEN_KEY, value={"token": token})
    except IntegrityError:
        return (await SystemSetting.get(key=METRICS_TOKEN_KEY)).value["token"]
    return token


async def reset_metrics_token() -> str:
    token = secrets.token_urlsafe(32)
    await SystemSetting.update_or_create(key=METRICS_TOKEN_KEY, defaults={"value": {"token": token}})
    return token


async def inference_audit_enabled() -> bool:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL:
        return _cache[1]
    row = await SystemSetting.get_or_none(key=INFERENCE_AUDIT_KEY)
    enabled = bool(row.value) if row is not None else False
    _cache = (now, enabled)
    return enabled


async def set_inference_audit_enabled(enabled: bool) -> bool:
    global _cache
    row = await SystemSetting.get_or_none(key=INFERENCE_AUDIT_KEY)
    if row is None:
        await SystemSetting.create(key=INFERENCE_AUDIT_KEY, value=enabled)
    else:
        row.value = enabled
        await row.save()
    _cache = (time.monotonic(), enabled)
    return enabled


async def keyword_filter_enabled() -> bool:
    row = await SystemSetting.get_or_none(key=KEYWORD_FILTER_KEY)
    return bool(row.value) if row is not None else False


async def set_keyword_filter_enabled(enabled: bool) -> bool:
    from app.services.content_filter import clear_filter_cache

    row = await SystemSetting.get_or_none(key=KEYWORD_FILTER_KEY)
    if row is None:
        await SystemSetting.create(key=KEYWORD_FILTER_KEY, value=enabled)
    else:
        row.value = enabled
        await row.save()
    clear_filter_cache()
    return enabled


def _normalize_ai_audit(value) -> dict:
    raw = value if isinstance(value, dict) else {}
    model = " ".join(str(raw.get("model") or "").split())[:64]
    return {
        "enabled": bool(raw.get("enabled")),
        "model": model,
    }


async def secret_scan_enabled() -> bool:
    global _secret_cache
    now = time.monotonic()
    if _secret_cache is not None and now - _secret_cache[0] < _CACHE_TTL:
        return _secret_cache[1]
    row = await SystemSetting.get_or_none(key=SECRET_SCAN_KEY)
    enabled = bool(row.value) if row is not None else False
    _secret_cache = (now, enabled)
    return enabled


async def set_secret_scan_enabled(enabled: bool) -> bool:
    from app.services.content_filter import clear_filter_cache

    global _secret_cache
    row = await SystemSetting.get_or_none(key=SECRET_SCAN_KEY)
    if row is None:
        await SystemSetting.create(key=SECRET_SCAN_KEY, value=enabled)
    else:
        row.value = enabled
        await row.save()
    _secret_cache = (time.monotonic(), enabled)
    clear_filter_cache()
    return enabled


async def ai_audit_config() -> dict:
    global _ai_cache
    now = time.monotonic()
    if _ai_cache is not None and now - _ai_cache[0] < _CACHE_TTL:
        return _ai_cache[1]
    row = await SystemSetting.get_or_none(key=AI_AUDIT_KEY)
    config = _normalize_ai_audit(row.value if row is not None else None)
    _ai_cache = (now, config)
    return config


async def set_ai_audit_config(*, enabled: bool, model: str) -> dict:
    global _ai_cache
    config = _normalize_ai_audit({"enabled": enabled, "model": model})
    row = await SystemSetting.get_or_none(key=AI_AUDIT_KEY)
    if row is None:
        await SystemSetting.create(key=AI_AUDIT_KEY, value=config)
    else:
        row.value = config
        await row.save()
    _ai_cache = (time.monotonic(), config)
    return config


def _clamp_int(value, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(number, low), high)


def default_gateway_config() -> dict:
    return {
        "log_retention_days": _clamp_int(settings.LOG_RETENTION_DAYS, 90, 0, 3650),
        "channel_health_threshold": _clamp_int(settings.CHANNEL_HEALTH_THRESHOLD, 3, 1, 100),
        "channel_health_check_interval": _clamp_int(settings.CHANNEL_HEALTH_CHECK_INTERVAL, 60, 10, 86400),
        "sticky_session_enabled": bool(settings.STICKY_SESSION_ENABLED),
        "sticky_session_ttl": _clamp_int(settings.STICKY_SESSION_TTL, 900, 60, 86400),
        "routing_strategy": "weighted",
        "model_fallbacks": {},
        "auto_cache_control": False,
        "budget_downgrade": {"threshold": 0.8, "rules": {}},
        "model_checks": {"health_enabled": True, "health_interval_seconds": 900,
                         "capability_enabled": True, "capability_interval_seconds": 86400},
    }


ROUTING_STRATEGIES = ("weighted", "least_busy", "latency")
MAX_FALLBACKS = 5
MAX_FALLBACK_RULES = 200


def _model_name(value) -> str:
    return " ".join(str(value or "").split())[:64]


def _normalize_fallbacks(value) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    rules: dict[str, list[str]] = {}
    for source, targets in list(value.items())[:MAX_FALLBACK_RULES]:
        name = _model_name(source)
        if not name or not isinstance(targets, list):
            continue
        chain: list[str] = []
        for target in targets:
            target_name = _model_name(target)
            if target_name and target_name != name and target_name not in chain:
                chain.append(target_name)
        if chain:
            rules[name] = chain[:MAX_FALLBACKS]
    return rules


def _normalize_downgrade(value) -> dict:
    raw = value if isinstance(value, dict) else {}
    try:
        threshold = min(max(float(raw.get("threshold", 0.8)), 0.1), 1.0)
    except (TypeError, ValueError):
        threshold = 0.8
    rules: dict[str, str] = {}
    source_rules = raw.get("rules") if isinstance(raw.get("rules"), dict) else {}
    for source, target in list(source_rules.items())[:MAX_FALLBACK_RULES]:
        name, target_name = _model_name(source), _model_name(target)
        if name and target_name and name != target_name:
            rules[name] = target_name
    return {"threshold": round(threshold, 2), "rules": rules}


def _normalize_gateway(value) -> dict:
    defaults = default_gateway_config()
    raw = value if isinstance(value, dict) else {}
    enabled = raw.get("sticky_session_enabled", defaults["sticky_session_enabled"])
    checks = raw.get("model_checks") if isinstance(raw.get("model_checks"), dict) else {}
    return {
        "log_retention_days": _clamp_int(raw.get("log_retention_days"), defaults["log_retention_days"], 0, 3650),
        "channel_health_threshold": _clamp_int(
            raw.get("channel_health_threshold"), defaults["channel_health_threshold"], 1, 100
        ),
        "channel_health_check_interval": _clamp_int(
            raw.get("channel_health_check_interval"), defaults["channel_health_check_interval"], 10, 86400
        ),
        "sticky_session_enabled": bool(enabled),
        "sticky_session_ttl": _clamp_int(raw.get("sticky_session_ttl"), defaults["sticky_session_ttl"], 60, 86400),
        "routing_strategy": (
            raw.get("routing_strategy")
            if raw.get("routing_strategy") in ROUTING_STRATEGIES
            else defaults["routing_strategy"]
        ),
        "model_fallbacks": _normalize_fallbacks(raw.get("model_fallbacks")),
        "auto_cache_control": bool(raw.get("auto_cache_control", defaults["auto_cache_control"])),
        "budget_downgrade": _normalize_downgrade(raw.get("budget_downgrade")),
        "model_checks": {
            "health_enabled": bool(checks.get("health_enabled", True)),
            "health_interval_seconds": _clamp_int(checks.get("health_interval_seconds"), 900, 60, 86400),
            "capability_enabled": bool(checks.get("capability_enabled", True)),
            "capability_interval_seconds": _clamp_int(checks.get("capability_interval_seconds"), 86400, 3600, 604800),
        },
    }


async def gateway_config() -> dict:
    global _gateway_cache
    now = time.monotonic()
    if _gateway_cache is not None and now - _gateway_cache[0] < _CACHE_TTL:
        return _gateway_cache[1]
    row = await SystemSetting.get_or_none(key=GATEWAY_KEY)
    config = _normalize_gateway(row.value if row is not None else None)
    _gateway_cache = (now, config)
    return config


async def set_gateway_config(config: dict) -> dict:
    global _gateway_cache
    stored = _normalize_gateway(config)
    row = await SystemSetting.get_or_none(key=GATEWAY_KEY)
    if row is None:
        await SystemSetting.create(key=GATEWAY_KEY, value=stored)
    else:
        row.value = stored
        await row.save()
    _gateway_cache = (time.monotonic(), stored)
    return stored


async def patch_gateway_config(delta: dict) -> dict:
    from tortoise.transactions import in_transaction
    global _gateway_cache
    async with in_transaction():
        await SystemSetting.get_or_create(key=GATEWAY_KEY, defaults={"value": default_gateway_config()})
        row = await SystemSetting.filter(key=GATEWAY_KEY).select_for_update().get()
        stored = _normalize_gateway({**_normalize_gateway(row.value), **delta})
        row.value = stored
        await row.save(update_fields=["value", "updated_at"])
    _gateway_cache = (time.monotonic(), stored)
    return stored


def clear_settings_cache() -> None:
    global _cache, _secret_cache, _ai_cache, _gateway_cache
    _cache = None
    _secret_cache = None
    _ai_cache = None
    _gateway_cache = None
