"""粘性会话：把同一会话的请求尽量固定到同一渠道。

固定同一上游渠道能提升 prompt 缓存命中率、降低多轮对话的上下文串味。
会话标识优先取请求头，取不到时用请求体前缀算指纹，这样无需客户端配合。
"""

import hashlib
import json
from typing import Any

from app.dependencies import get_redis

KEY_PREFIX = "five:sticky:"

# 兼容常见客户端与 sub2api 的会话头，session-id 来自 Codex（Starlette Headers 取值大小写不敏感）
SESSION_HEADERS = (
    "x-session-id", "session_id", "session-id", "x-conversation-id", "x-claude-code-session-id",
)


def _fingerprint_from_body(body: dict[str, Any]) -> str | None:
    """从请求体推导稳定的会话指纹。

    取 system 提示 + 首条 user 消息作为前缀——它在整段多轮对话中保持不变，
    因此同一会话的后续请求会得到相同指纹，从而粘到同一渠道。
    """
    parts: list[str] = []

    system = body.get("system")
    if system:
        parts.append(json.dumps(system, ensure_ascii=False, sort_keys=True))

    messages = body.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "user":
                parts.append(json.dumps(msg.get("content"), ensure_ascii=False, sort_keys=True))
                break

    if not parts:
        return None
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]


def _metadata_session(body: dict[str, Any]) -> str | None:
    """Claude Code puts "..._session_<uuid>" into metadata.user_id."""
    metadata = body.get("metadata")
    user_id = metadata.get("user_id") if isinstance(metadata, dict) else None
    if isinstance(user_id, str) and "session_" in user_id:
        return user_id.rsplit("session_", 1)[1].strip() or None
    return None


def session_identity(headers: Any, body: dict[str, Any]) -> str | None:
    for h in SESSION_HEADERS:
        v = headers.get(h)
        if v:
            return v.strip()
    if not isinstance(body, dict):
        return None
    return _metadata_session(body) or _fingerprint_from_body(body)


def session_log_id(api_key_id: int, headers: Any, body: dict[str, Any]) -> str:
    """Stable id written to request logs, so spend can be grouped by session."""
    raw = session_identity(headers, body)
    if not raw:
        return ""
    return hashlib.sha256(f"{api_key_id}\x1f{raw}".encode("utf-8")).hexdigest()[:32]


async def make_session_key(api_key_id: int, headers: Any, body: dict[str, Any]) -> str | None:
    """构造 Redis 会话键；未启用或无法识别会话时返回 None。"""
    from app.services.settings_service import gateway_config

    if not (await gateway_config())["sticky_session_enabled"]:
        return None

    session_id = session_identity(headers, body)
    if not session_id:
        return None

    return f"{KEY_PREFIX}{api_key_id}:{session_id}"


async def get_sticky_channel(session_key: str | None) -> int | None:
    """返回该会话上次成功使用的渠道 ID。"""
    if not session_key:
        return None
    r = await get_redis()
    val = await r.get(session_key)
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


async def bind_sticky_channel(session_key: str | None, channel_id: int) -> None:
    """请求成功后回写绑定并刷新 TTL。"""
    if not session_key:
        return
    from app.services.settings_service import gateway_config

    r = await get_redis()
    ttl = (await gateway_config())["sticky_session_ttl"]
    await r.set(session_key, channel_id, ex=ttl)
