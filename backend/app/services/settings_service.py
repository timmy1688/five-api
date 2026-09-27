"""系统设置。推理审计以这里的开关为准，单个 Key 仍可单独打开。

网关运行参数存在 system_settings。没有记录时用环境变量里的默认值。
"""

import time

from app.config import settings
from app.models import SystemSetting

INFERENCE_AUDIT_KEY = "inference_audit_enabled"
KEYWORD_FILTER_KEY = "keyword_filter_enabled"
SECRET_SCAN_KEY = "secret_scan_enabled"
AI_AUDIT_KEY = "ai_audit"
GATEWAY_KEY = "gateway"
_CACHE_TTL = 2.0
_cache: tuple[float, bool] | None = None
_secret_cache: tuple[float, bool] | None = None
_ai_cache: tuple[float, dict] | None = None
_gateway_cache: tuple[float, dict] | None = None

_AI_DEFAULT = {"enabled": False, "model": "", "fail_closed": False}


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
        "fail_closed": bool(raw.get("fail_closed")),
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


def peek_ai_audit_config() -> dict | None:
    """命中进程缓存时直接返回。请求路径用它避免为关闭的审计再挂后台任务。"""
    if _ai_cache is None or time.monotonic() - _ai_cache[0] >= _CACHE_TTL:
        return None
    return _ai_cache[1]


async def ai_audit_config() -> dict:
    global _ai_cache
    now = time.monotonic()
    if _ai_cache is not None and now - _ai_cache[0] < _CACHE_TTL:
        return _ai_cache[1]
    row = await SystemSetting.get_or_none(key=AI_AUDIT_KEY)
    config = _normalize_ai_audit(row.value if row is not None else None)
    _ai_cache = (now, config)
    return config


async def set_ai_audit_config(*, enabled: bool, model: str, fail_closed: bool) -> dict:
    global _ai_cache
    config = _normalize_ai_audit({"enabled": enabled, "model": model, "fail_closed": fail_closed})
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
    }


def _normalize_gateway(value) -> dict:
    defaults = default_gateway_config()
    raw = value if isinstance(value, dict) else {}
    enabled = raw.get("sticky_session_enabled", defaults["sticky_session_enabled"])
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


def clear_settings_cache() -> None:
    global _cache, _secret_cache, _ai_cache, _gateway_cache
    _cache = None
    _secret_cache = None
    _ai_cache = None
    _gateway_cache = None
