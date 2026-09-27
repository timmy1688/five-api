"""AI 审计由审计页按人选中后才调用，不跟在每次请求后面。

送去模型的内容是：系统提示最多 400 字，加上最后一条用户消息最多 1200 字。
更早的对话、图片和模型回复都不送。审计页会把这个 Key 保存过的请求全部送审。
结论只要一行 JSON。思考模式会把输出额度用完，正文变成空，所以先关掉思考。
上游不接受这个参数时，再用更大的额度重试一次。
等待时间用渠道自己的超时，不再单独加一个几秒的审查超时。
相同摘录 10 分钟内不重复调用。结论写回请求日志的 ai_review。
审计调用不走用户配额，失败时不改渠道健康状态。
"""

import asyncio
import hashlib
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SYSTEM_CHARS = 400
USER_CHARS = 1200
MIN_CHARS = 24
MAX_OUTPUT_TOKENS = 128
_FALLBACK_OUTPUT_TOKENS = 1024
CACHE_TTL = 600
_CACHE_PREFIX = "five:ai-audit:"
_CATEGORIES = {"credential", "personal", "confidential"}

_SYSTEM_PROMPT = (
    "You are a data-loss filter. Decide whether the excerpt contains secrets, "
    "credentials, or private personal data that must not be sent to a model. "
    'Reply with one JSON object only: {"block":true,"category":"credential"} '
    'or {"block":false}. category is credential, personal, or confidential. '
    "Do not repeat the excerpt."
)


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit]


def _parts_from(value: Any, parts: list[str]) -> None:
    if isinstance(value, str):
        if value:
            parts.append(value)
        return
    if isinstance(value, list):
        for item in value:
            _parts_from(item, parts)
        return
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
        content = value.get("content")
        if content is not None and content is not value:
            _parts_from(content, parts)


def _text_of(value: Any) -> str:
    parts: list[str] = []
    _parts_from(value, parts)
    return "\n".join(parts)


def _last_role_text(body: dict, role: str) -> str:
    messages = body.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == role:
                return _text_of(message.get("content"))
    return ""


def _last_user_text(body: dict) -> str:
    text = _last_role_text(body, "user")
    if text:
        return text
    for key in ("prompt", "input"):
        if body.get(key) is not None:
            return _text_of(body.get(key))
    return ""


def build_excerpt(body: dict | None) -> str:
    """只保留系统提示和最后一条用户消息。历史轮次不进入模型。"""
    if not body:
        return ""
    system = _text_of(body.get("system")) or _last_role_text(body, "system")
    system = _clip(system, SYSTEM_CHARS)
    user = _clip(_last_user_text(body), USER_CHARS)
    lines = []
    if system:
        lines.append(f"system:\n{system}")
    if user:
        lines.append(f"user:\n{user}")
    return "\n".join(lines)


def parse_verdict(raw: str) -> tuple[bool, str]:
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("ai audit verdict is not json")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("ai audit verdict is not an object")
    category = str(data.get("category") or "other")
    if category not in _CATEGORIES:
        category = "other"
    return bool(data.get("block")), category


def _cache_key(excerpt: str) -> str:
    digest = hashlib.sha256(excerpt.encode()).hexdigest()
    return f"{_CACHE_PREFIX}{digest}"


async def _cached_verdict(excerpt: str) -> tuple[bool, str] | None:
    try:
        from app.dependencies import get_redis

        raw = await (await get_redis()).get(_cache_key(excerpt))
    except Exception:
        logger.warning("ai audit cache read failed")
        return None
    if raw is None:
        return None
    if raw == "0":
        return False, ""
    if isinstance(raw, str) and raw.startswith("1:"):
        category = raw[2:]
        if category not in _CATEGORIES and category != "other":
            category = "other"
        return True, category
    return None


async def _store_verdict(excerpt: str, block: bool, category: str) -> None:
    value = f"1:{category}" if block else "0"
    try:
        from app.dependencies import get_redis

        await (await get_redis()).set(_cache_key(excerpt), value, ex=CACHE_TTL)
    except Exception:
        logger.warning("ai audit cache write failed")


def _message_text(payload: dict) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        text = "".join(parts)
        if text.strip():
            return text
    return ""


def _request_variants(model: str, excerpt: str) -> list[dict]:
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": excerpt},
    ]
    return [
        {
            "model": model,
            "messages": messages,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "temperature": 0,
            "stream": False,
            "thinking": {"type": "disabled"},
        },
        {
            "model": model,
            "messages": messages,
            "max_tokens": _FALLBACK_OUTPUT_TOKENS,
            "temperature": 0,
            "stream": False,
        },
    ]


async def _complete(model: str, excerpt: str) -> str:
    from app.providers.registry import resolve_candidates

    candidates = await resolve_candidates(model, preferred_protocol="openai")
    channel, provider_cls = candidates[0]
    provider = provider_cls(channel)
    try:
        for body_in in _request_variants(model, excerpt):
            path, headers, body = provider.transform_request(body_in, "/v1/chat/completions")
            response = await provider.client.post(
                path,
                json=body,
                headers=headers,
                timeout=httpx.Timeout(channel.timeout),
            )
            # 关掉思考是给会思考的模型用的。不认识这个字段的上游改走下一次请求。
            if response.status_code == 400 and "thinking" in body_in:
                continue
            response.raise_for_status()
            text = _message_text(response.json())
            if text.strip():
                return text
        raise ValueError("ai audit model returned no verdict")
    finally:
        await provider.close()


_MAX_PENDING = 8
_slots = asyncio.Semaphore(2)
_pending = 0
_tasks: set[asyncio.Task] = set()


def schedule_ai_review(request_id: str, body: dict | None) -> None:
    """请求已经记完日志后再排队。队列满了就跳过，不让审查堆在请求后面。"""
    from app.services.settings_service import peek_ai_audit_config

    cached = peek_ai_audit_config()
    if cached is not None and (not cached["enabled"] or not cached["model"]):
        return
    task = asyncio.create_task(_review(request_id, body))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def drain_ai_reviews() -> None:
    if _tasks:
        await asyncio.gather(*list(_tasks))


async def _mark(request_id: str, verdict: str) -> None:
    from app.models import RequestLog

    await RequestLog.filter(request_id=request_id).update(ai_review=verdict[:32])


async def _review(request_id: str, body: dict | None) -> None:
    global _pending
    from app.services.settings_service import ai_audit_config

    try:
        config = await ai_audit_config()
        if not config["enabled"] or not config["model"]:
            return
        excerpt = build_excerpt(body)
        if len(excerpt) < MIN_CHARS:
            return
        if _pending >= _MAX_PENDING:
            logger.warning("ai audit skipped because the review queue is full")
            await _mark(request_id, "skipped")
            return
        _pending += 1
        try:
            async with _slots:
                verdict = await _verdict(config["model"], excerpt)
        finally:
            _pending -= 1
        await _mark(request_id, verdict)
    except Exception:
        logger.warning("ai audit review failed for %s", request_id)
        try:
            await _mark(request_id, "unavailable")
        except Exception:
            logger.warning("ai audit could not record a verdict for %s", request_id)


async def _verdict(model: str, excerpt: str) -> str:
    cached = await _cached_verdict(excerpt)
    if cached is None:
        raw = await _complete(model, excerpt)
        block, category = parse_verdict(raw)
        await _store_verdict(excerpt, block, category)
    else:
        block, category = cached
    if block:
        return f"flagged:{category}"
    return "clear"
