"""Alert webhooks for Feishu, DingTalk, WeCom and plain JSON receivers.

Events fire from the request path, so every check stays cheap when alerts are
off and delivery runs in background tasks. Redis SET NX keeps one message per
event subject until the dedupe window passes.
"""

import asyncio
import base64
import hashlib
import hmac
import logging
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlsplit

import httpx

from app import dependencies
from app.models import SystemSetting
from app.utils.secrets import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

ALERTS_KEY = "alerts"
WEBHOOK_TYPES = ("feishu", "dingtalk", "wecom", "generic")
EVENTS = ("budget", "channel", "errors")
MAX_WEBHOOKS = 10
BUDGET_DEDUPE = 12 * 3600
CHANNEL_DEDUPE = 300
ERROR_DEDUPE = 600
_CACHE_TTL = 2.0
_cache: tuple[float, dict] | None = None
_tasks: set[asyncio.Task] = set()


def default_config() -> dict:
    return {
        "enabled": False,
        "webhooks": [],
        "events": {event: True for event in EVENTS},
        "budget_threshold": 0.9,
        "error_threshold": 0.5,
        "error_min_requests": 20,
    }


def _number(value, default: float, low: float, high: float) -> float:
    try:
        return min(max(float(value), low), high)
    except (TypeError, ValueError):
        return default


def _normalize(value) -> dict:
    raw = value if isinstance(value, dict) else {}
    defaults = default_config()
    events = raw.get("events") if isinstance(raw.get("events"), dict) else {}
    hooks = []
    for hook in (raw.get("webhooks") if isinstance(raw.get("webhooks"), list) else [])[:MAX_WEBHOOKS]:
        if not isinstance(hook, dict) or hook.get("type") not in WEBHOOK_TYPES or not hook.get("url"):
            continue
        hooks.append({
            "id": str(hook.get("id") or uuid.uuid4().hex[:8])[:16],
            "name": " ".join(str(hook.get("name") or "").split())[:64] or hook["type"],
            "type": hook["type"],
            "url": str(hook["url"]),
            "secret": str(hook.get("secret") or ""),
        })
    return {
        "enabled": bool(raw.get("enabled", defaults["enabled"])),
        "webhooks": hooks,
        "events": {event: bool(events.get(event, True)) for event in EVENTS},
        "budget_threshold": round(_number(raw.get("budget_threshold"), 0.9, 0.1, 1.0), 2),
        "error_threshold": round(_number(raw.get("error_threshold"), 0.5, 0.05, 1.0), 2),
        "error_min_requests": int(_number(raw.get("error_min_requests"), 20, 1, 10000)),
    }


async def alert_config() -> dict:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL:
        return _cache[1]
    row = await SystemSetting.get_or_none(key=ALERTS_KEY)
    config = _normalize(row.value if row is not None else None)
    _cache = (now, config)
    return config


def clear_alert_cache() -> None:
    global _cache
    _cache = None


def mask_url(encrypted: str) -> str:
    plain = decrypt_secret(encrypted)
    parts = urlsplit(plain)
    tail = plain[-4:] if len(plain) > 12 else ""
    return f"{parts.scheme}://{parts.netloc}/••••{tail}" if parts.netloc else "••••"


def public_config(config: dict) -> dict:
    return {
        **config,
        "webhooks": [
            {
                "id": hook["id"], "name": hook["name"], "type": hook["type"],
                "url": mask_url(hook["url"]), "has_secret": bool(hook["secret"]),
            }
            for hook in config["webhooks"]
        ],
    }


async def save_config(body: dict) -> dict:
    """Webhooks sent back with their masked URL or an empty secret keep the stored values."""
    current = {hook["id"]: hook for hook in (await alert_config())["webhooks"]}
    hooks = []
    for hook in body.get("webhooks") or []:
        stored = current.get(str(hook.get("id") or ""))
        url = str(hook.get("url") or "").strip()
        if stored is not None and (not url or url == mask_url(stored["url"])):
            encrypted_url = stored["url"]
        elif url.startswith(("https://", "http://")):
            encrypted_url = encrypt_secret(url)
        else:
            continue
        secret = str(hook.get("secret") or "").strip()
        if secret:
            encrypted_secret = encrypt_secret(secret)
        elif stored is not None and not hook.get("clear_secret"):
            encrypted_secret = stored["secret"]
        else:
            encrypted_secret = ""
        hooks.append({**hook, "url": encrypted_url, "secret": encrypted_secret})
    config = _normalize({**body, "webhooks": hooks})
    row = await SystemSetting.get_or_none(key=ALERTS_KEY)
    if row is None:
        await SystemSetting.create(key=ALERTS_KEY, value=config)
    else:
        row.value = config
        await row.save()
    clear_alert_cache()
    return config


def build_request(hook: dict, event: str, title: str, text: str, data: dict) -> tuple[str, dict]:
    url = decrypt_secret(hook["url"])
    secret = decrypt_secret(hook["secret"]) if hook["secret"] else ""
    content = f"{title}\n{text}"
    if hook["type"] == "feishu":
        payload: dict = {"msg_type": "text", "content": {"text": content}}
        if secret:
            timestamp = str(int(time.time()))
            digest = hmac.new(f"{timestamp}\n{secret}".encode(), b"", hashlib.sha256).digest()
            payload.update(timestamp=timestamp, sign=base64.b64encode(digest).decode())
        return url, payload
    if hook["type"] == "dingtalk":
        if secret:
            timestamp = str(int(time.time() * 1000))
            digest = hmac.new(secret.encode(), f"{timestamp}\n{secret}".encode(), hashlib.sha256).digest()
            sign = quote_plus(base64.b64encode(digest).decode())
            url += ("&" if "?" in url else "?") + f"timestamp={timestamp}&sign={sign}"
        return url, {"msgtype": "text", "text": {"content": content}}
    if hook["type"] == "wecom":
        return url, {"msgtype": "text", "text": {"content": content}}
    return url, {
        "event": event,
        "title": title,
        "text": text,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def _post(client: httpx.AsyncClient, hook: dict, event: str, title: str, text: str, data: dict) -> dict:
    """IM bots answer HTTP 200 with an error code in the body, so both are checked."""
    try:
        url, payload = build_request(hook, event, title, text, data)
        resp = await client.post(url, json=payload)
        error = ""
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if isinstance(body, dict):
            code = body.get("code", body.get("errcode", body.get("StatusCode", 0)))
            if code not in (0, None):
                error = str(body.get("msg") or body.get("errmsg") or code)[:200]
        if resp.status_code >= 400 and not error:
            error = f"HTTP {resp.status_code}"
        return {"id": hook["id"], "name": hook["name"], "ok": not error, "error": error}
    except Exception as exc:
        return {"id": hook["id"], "name": hook["name"], "ok": False, "error": type(exc).__name__}


async def deliver(hooks: list[dict], event: str, title: str, text: str, data: dict) -> list[dict]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        results = await asyncio.gather(*(_post(client, hook, event, title, text, data) for hook in hooks))
    for result in results:
        if not result["ok"]:
            logger.warning("alert webhook %s failed: %s", result["name"], result["error"])
    return list(results)


async def notify(event: str, subject: str, title: str, text: str, data: dict, dedupe_seconds: int) -> bool:
    config = await alert_config()
    if not config["enabled"] or not config["events"].get(event) or not config["webhooks"]:
        return False
    redis = await dependencies.get_redis()
    if not await redis.set(f"five:alert:{event}:{subject}", "1", ex=dedupe_seconds, nx=True):
        return False
    task = asyncio.create_task(deliver(config["webhooks"], event, f"[Five API] {title}", text, data))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True


async def drain_alerts() -> None:
    if _tasks:
        await asyncio.gather(*list(_tasks))


def _active(config: dict | None, event: str) -> bool:
    return bool(config and config["enabled"] and config["webhooks"] and config["events"].get(event))


async def channel_opened(channel_id: int, failures: int) -> None:
    if not _active(await alert_config(), "channel"):
        return
    from app.models import Channel

    channel = await Channel.get_or_none(id=channel_id)
    name = channel.name if channel else f"#{channel_id}"
    await notify(
        "channel", f"open:{channel_id}", f"渠道熔断 {name}",
        f"渠道 {name} 连续失败 {failures} 次，已暂停分配请求，后台探测恢复后自动启用。",
        {"channel_id": channel_id, "channel": name, "failures": failures, "state": "open"},
        CHANNEL_DEDUPE,
    )


async def channel_recovered(channel_id: int) -> None:
    if not _active(await alert_config(), "channel"):
        return
    from app.models import Channel

    channel = await Channel.get_or_none(id=channel_id)
    name = channel.name if channel else f"#{channel_id}"
    redis = await dependencies.get_redis()
    await redis.delete(f"five:alert:channel:open:{channel_id}")
    await notify(
        "channel", f"recover:{channel_id}", f"渠道恢复 {name}",
        f"渠道 {name} 已恢复，重新参与路由。",
        {"channel_id": channel_id, "channel": name, "state": "recovered"},
        CHANNEL_DEDUPE,
    )


async def record_outcome(status_code: int) -> None:
    """Counts requests per minute and alerts once the share of 5xx crosses the threshold."""
    config = await alert_config()
    if not _active(config, "errors"):
        return
    redis = await dependencies.get_redis()
    minute = int(time.time() // 60)
    total_key, error_key = f"five:alert:req:{minute}", f"five:alert:err:{minute}"
    total = await redis.incr(total_key)
    if total == 1:
        await redis.expire(total_key, 180)
    if status_code < 500:
        return
    errors = await redis.incr(error_key)
    if errors == 1:
        await redis.expire(error_key, 180)
    if total < config["error_min_requests"] or errors / total < config["error_threshold"]:
        return
    await notify(
        "errors", "spike", "错误率告警",
        f"最近一分钟 {total} 个请求里 {errors} 个返回 5xx（{errors / total:.0%}）。",
        {"requests": total, "errors": errors, "rate": round(errors / total, 4)},
        ERROR_DEDUPE,
    )


async def check_budget(api_key_id: int) -> None:
    config = await alert_config()
    if not _active(config, "budget"):
        return
    from app.models import APIKey, Team
    from app.services.spend_windows import normalize_limits, window_spend

    threshold = config["budget_threshold"]
    key = await APIKey.get_or_none(id=api_key_id)
    if key is None:
        return
    owners = [("key", key.id, f"Key {key.name}", key)]
    if key.team_id:
        team = await Team.get_or_none(id=key.team_id)
        if team is not None:
            owners.append(("team", team.id, f"团队 {team.name}", team))
    for scope, owner_id, label, owner in owners:
        budgets = []
        total = float(owner.quota_total)
        if total > 0:
            budgets.append(("quota", "总额度", float(owner.quota_used), total))
        caps = normalize_limits(owner.window_limits)
        if caps:
            spent = await window_spend(scope, owner_id)
            budgets.extend((window, f"{window} 滚动限额", spent[window], cap) for window, cap in caps.items())
        for budget, budget_label, used, cap in budgets:
            if cap <= 0 or used / cap < threshold:
                continue
            await notify(
                "budget", f"{scope}:{owner_id}:{budget}", f"预算预警 {label}",
                f"{label} 的{budget_label}已用 ${used:.4f} / ${cap:.4f}（{used / cap:.0%}）。",
                {"scope": scope, "id": owner_id, "budget": budget, "used": round(used, 6), "limit": cap},
                BUDGET_DEDUPE,
            )
