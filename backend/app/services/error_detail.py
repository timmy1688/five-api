"""把失败分成网关自己的拒绝，以及官网或渠道商返回的上游错误。"""

import json
from urllib.parse import urlparse

import httpx

# 这些主机是厂商自己的 API。其余地址按渠道商中转处理。
OFFICIAL_HOSTS = {
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "dashscope.aliyuncs.com",
    "api.deepseek.com",
    "api.mistral.ai",
    "api.groq.com",
    "api.x.ai",
}

MAX_ERROR_CHARS = 8_000


def classify_base_url(base_url: str) -> str:
    host = (urlparse(base_url).hostname or "").lower().rstrip(".")
    if host in OFFICIAL_HOSTS or host.endswith(".openai.azure.com"):
        return "official"
    return "reseller"


def _clip(text: str) -> str:
    if len(text) <= MAX_ERROR_CHARS:
        return text
    return text[:MAX_ERROR_CHARS] + "\n…[truncated]"


def _response_text(response: httpx.Response) -> str:
    try:
        return response.text or ""
    except Exception:
        return ""


def _message_from_body(text: str, fallback: str) -> str:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        stripped = text.strip()
        return stripped or fallback
    if not isinstance(data, dict):
        return fallback
    error = data.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    if isinstance(error, str) and error:
        return error
    if data.get("message"):
        return str(data["message"])
    return fallback


def describe_upstream_failure(exc: Exception, base_url: str) -> dict:
    """上游已经发出请求之后的失败。"""
    origin = classify_base_url(base_url)
    upstream_status = 0
    upstream_error = ""
    summary = str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        upstream_status = exc.response.status_code
        upstream_error = _response_text(exc.response)
        summary = _message_from_body(upstream_error, summary)
    elif isinstance(exc, httpx.TimeoutException):
        summary = "Upstream timeout"
        upstream_error = summary
    elif isinstance(exc, httpx.NetworkError):
        summary = f"Upstream network error: {exc}"
        upstream_error = summary
    else:
        upstream_error = summary
    return {
        "error_origin": origin,
        "upstream_status_code": upstream_status,
        "upstream_error": _clip(upstream_error),
        "error_message": _clip(summary),
    }


def gateway_failure(message: str) -> dict:
    return {
        "error_origin": "gateway",
        "upstream_status_code": 0,
        "upstream_error": "",
        "error_message": _clip(message),
    }
