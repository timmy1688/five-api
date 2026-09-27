"""可选的推理审计：按 API Key 或系统开关，只保存请求摘录。

回复不入库。回复又长，又和泄漏排查关系不大；关键词和密钥扫描仍在返回前就地检查，不依赖把正文存下来。
超长请求保留开头和结尾，并丢掉工具定义，只留工具名。这样 JSON 仍然完整，最新一轮对话不会被截掉。
"""

import json
from typing import Any

from fastapi.responses import JSONResponse

# utf8mb4 下约 16k 字符仍能放进 TEXT/LONGTEXT，并避免单条日志把表撑得过大。
MAX_AUDIT_CHARS = 16_000


def clip(text: str) -> str:
    if len(text) <= MAX_AUDIT_CHARS:
        return text
    return text[:MAX_AUDIT_CHARS] + "\n…[truncated]"


def _clip_middle(text: str, limit: int) -> str:
    """超长文本留开头和结尾。用户真正的问题经常在长提示的末尾。"""
    if len(text) <= limit:
        return text
    mark = f"…[{len(text)} chars]…"
    keep = limit - len(mark)
    if keep < 40:
        return text[:limit]
    head = keep // 2
    return text[:head] + mark + text[-(keep - head):]


def _tool_names(tools: list) -> list[str]:
    names: list[str] = []
    for tool in tools:
        if isinstance(tool, dict):
            name = tool.get("name")
            function = tool.get("function")
            if not name and isinstance(function, dict):
                name = function.get("name")
            names.append(str(name or "tool"))
        else:
            names.append(str(tool)[:80])
    if len(names) > 80:
        hidden = len(names) - 79
        names = names[:79] + [f"…[{hidden} more tools]"]
    return names


def _shrink_messages(messages: list) -> list:
    """对话保留最近的轮次。只留前 40 条会把最新的用户消息截掉。"""
    items = [_shrink(item) for item in messages]
    if len(items) <= 40:
        return items
    omitted = len(items) - 39
    return [{"role": "user", "content": f"[{omitted} earlier messages omitted]"}] + items[-39:]


def _shrink(value: Any) -> Any:
    """丢掉内联图片、工具定义和超长字符串，审计里保留对话结构即可。"""
    if isinstance(value, dict):
        shrunk = {}
        for key, item in value.items():
            if key in {"data", "url", "image_url"} and isinstance(item, str) and len(item) > 180:
                shrunk[key] = f"[omitted {len(item)} chars]"
            elif key == "messages" and isinstance(item, list):
                shrunk[key] = _shrink_messages(item)
            elif key == "tools" and isinstance(item, list):
                shrunk[key] = _tool_names(item)
            else:
                shrunk[key] = _shrink(item)
        return shrunk
    if isinstance(value, list):
        items = [_shrink(item) for item in value[:40]]
        if len(value) > 40:
            items.append(f"…[{len(value) - 40} more]")
        return items
    if isinstance(value, str) and len(value) > 4000:
        return _clip_middle(value, 4000)
    return value


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _retighten(value: Any, limit: int) -> Any:
    if isinstance(value, dict):
        return {key: _retighten(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_retighten(item, limit) for item in value]
    if isinstance(value, str) and len(value) > limit:
        return _clip_middle(value, limit)
    return value


def _fit(body: dict) -> dict:
    """压到字符上限以内，并始终留下最后一条消息。"""
    for limit in (2000, 800, 300):
        body = _retighten(body, limit)
        messages = body.get("messages")
        if isinstance(messages, list):
            while len(messages) > 1 and len(_dump(body)) > MAX_AUDIT_CHARS:
                messages.pop(0)
        if len(_dump(body)) <= MAX_AUDIT_CHARS:
            return body
    body.pop("tools", None)
    messages = body.get("messages")
    if isinstance(messages, list) and messages:
        body["messages"] = messages[-1:]
    body = _retighten(body, 400)
    if len(_dump(body)) <= MAX_AUDIT_CHARS:
        return body
    return {
        "model": body.get("model", ""),
        "messages": [{"role": "user", "content": "[request omitted: too large]"}],
    }


def request_excerpt(body: dict | None) -> str:
    if not body:
        return ""
    shrunk = _shrink(body)
    if len(_dump(shrunk)) <= MAX_AUDIT_CHARS:
        return _dump(shrunk)
    return _dump(_fit(shrunk))


def _block_lines(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content] if content else []
    if isinstance(content, list):
        lines: list[str] = []
        for item in content:
            lines.extend(_block_lines(item))
        return [line for line in lines if line]
    if isinstance(content, dict):
        kind = content.get("type")
        if kind in {None, "text"} and isinstance(content.get("text"), str):
            return [content["text"]] if content["text"] else []
        if kind == "tool_use":
            return [_dump({"tool": content.get("name"), "input": content.get("input")})]
        if kind == "tool_result":
            inner = _block_lines(content.get("content"))
            return ["tool_result:\n" + "\n".join(inner)] if inner else ["tool_result"]
        if "content" in content:
            return _block_lines(content.get("content"))
        return []
    if content is None:
        return []
    return [str(content)]


def saved_transcript(stored: str) -> str:
    """把已保存的请求排成可读对话。旧数据如果被截成无效 JSON，就原样显示。"""
    if not stored:
        return ""
    try:
        body = json.loads(stored)
    except json.JSONDecodeError:
        return stored
    if not isinstance(body, dict):
        return stored
    lines: list[str] = []
    system = _block_lines(body.get("system"))
    if system:
        lines.append("system:\n" + "\n".join(system))
    tools = body.get("tools")
    if isinstance(tools, list) and tools and all(isinstance(name, str) for name in tools):
        lines.append("tools: " + ", ".join(tools))
    messages = body.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "message")
            parts = _block_lines(message.get("content"))
            for call in message.get("tool_calls") or []:
                if isinstance(call, dict):
                    parts.append(_dump(call))
            lines.append(f"{role}:\n" + "\n".join(parts))
    if not messages:
        prompt = _block_lines(body.get("prompt"))
        if not prompt:
            prompt = _block_lines(body.get("input"))
        if prompt:
            lines.append("user:\n" + "\n".join(prompt))
    text = "\n\n".join(line for line in lines if line.strip())
    return text or stored


def _content_from_message(message: dict) -> str:
    parts: list[str] = []
    content = message.get("content")
    if isinstance(content, str) and content:
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text"):
                parts.append(block["text"])
            elif block.get("type") == "tool_use":
                parts.append(json.dumps(
                    {"tool": block.get("name"), "input": block.get("input")},
                    ensure_ascii=False,
                    default=str,
                ))
    for call in message.get("tool_calls") or []:
        if isinstance(call, dict):
            parts.append(json.dumps(call, ensure_ascii=False, default=str))
    return "\n".join(parts)


def response_visible_text(response: Any) -> str:
    """从非流式响应里取出助手文本。拿不到时保留截断后的 JSON。"""
    data = response
    if isinstance(response, JSONResponse):
        raw = response.body
        try:
            data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            return clip(str(raw))
    if not isinstance(data, dict):
        return clip(str(data))

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = (choices[0] or {}).get("message") or {}
        text = _content_from_message(message)
        if text:
            return text

    content = data.get("content")
    if isinstance(content, list):
        text = _content_from_message({"content": content})
        if text:
            return text
    if isinstance(content, str) and content:
        return content

    return json.dumps(_shrink(data), ensure_ascii=False, default=str)


def sse_visible_text(line: str) -> str:
    """从一条 SSE 里取出新增的可见文本。usage 事件返回空字符串。"""
    stripped = line.strip()
    if not stripped.startswith("data:"):
        return ""
    payload = stripped[5:].strip()
    if not payload or payload == "[DONE]":
        return ""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""

    pieces: list[str] = []
    for choice in data.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") or {}
        content = delta.get("content")
        if isinstance(content, str) and content:
            pieces.append(content)
        for call in delta.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            arguments = (call.get("function") or {}).get("arguments")
            if arguments:
                pieces.append(arguments)

    delta = data.get("delta") or {}
    if isinstance(delta, dict):
        if delta.get("type") == "text_delta" and delta.get("text"):
            pieces.append(delta["text"])
        elif delta.get("type") == "input_json_delta" and delta.get("partial_json"):
            pieces.append(delta["partial_json"])
    return "".join(pieces)


_POLICIES = {"on", "off"}


def audit_policy(api_key) -> str:
    value = getattr(api_key, "audit_policy", "on") or "on"
    return value if value in _POLICIES else "on"


def security_exempt(api_key) -> bool:
    """关闭：不拦截、不审查、不保存请求正文。"""
    return audit_policy(api_key) == "off"


async def open_audit(api_key, request_body: dict | None) -> "AuditBuffer | None":
    """关闭的 Key 不记正文。开启的 Key 跟随系统推理审计开关。"""
    from app.services.settings_service import inference_audit_enabled

    if security_exempt(api_key) or not await inference_audit_enabled():
        return None
    return AuditBuffer(request_body)


class AuditBuffer:
    """一次请求的审计缓冲。未开启时不要创建。只保留请求。"""

    def __init__(self, request_body: dict | None):
        self.request_text = request_excerpt(request_body)

    def set_request(self, request_body: dict | None) -> None:
        self.request_text = request_excerpt(request_body)
