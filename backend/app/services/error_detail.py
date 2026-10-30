"""把失败分成网关自己的拒绝，以及渠道（上游）返回的错误。"""

import json

import httpx

from app.providers.base import ERROR_IN_OK
from app.services.failover import NoReadyUpstreamKey, is_credential_error
from app.services.redaction import redact

MAX_ERROR_CHARS = 8_000


def _clip(text: str) -> str:
    text = redact(text)
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


def describe_upstream_failure(exc: Exception) -> dict:
    """上游已经发出请求之后的失败。"""
    upstream_status = 0
    upstream_error = ""
    summary = str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        upstream_status = 200 if exc.response.extensions.get(ERROR_IN_OK) else exc.response.status_code
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
        "error_origin": "channel",
        "upstream_status_code": upstream_status,
        "upstream_error": _clip(upstream_error),
        "error_message": _clip(summary),
    }


def upstream_json_error(exc: Exception) -> tuple[int, dict] | None:
    """4xx JSON from the upstream, returned to the client without rewriting.

    An error body sent with HTTP 200 is returned too, whatever status it maps
    to. Other 5xx and non-JSON bodies stay on the gateway's own error shape. A body
    larger than the log clip is not forwarded, so a huge page cannot become
    the client response.
    """
    if not isinstance(exc, httpx.HTTPStatusError) or is_credential_error(exc):
        return None
    status = exc.response.status_code
    if status < 400 or (status >= 500 and not exc.response.extensions.get(ERROR_IN_OK)):
        return None
    text = _response_text(exc.response)
    if not text or len(text) > MAX_ERROR_CHARS:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return status, redact(data)


def client_status(exc: Exception) -> int:
    """Status sent downstream: upstream 4xx JSON keeps its code, the rest is 502.

    Upstream 401/403 concern the platform's credentials, so the customer never sees them as its own.
    """
    if isinstance(exc, NoReadyUpstreamKey):
        return 503
    passed = upstream_json_error(exc)
    return passed[0] if passed is not None else 502


def client_message(exc: Exception) -> str:
    """Client-facing summary. httpx messages carry the upstream URL, which stays in the log."""
    if isinstance(exc, NoReadyUpstreamKey):
        return "Upstream capacity temporarily unavailable"
    if is_credential_error(exc):
        return "Upstream credentials unavailable"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Upstream error: HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "Upstream error: timeout"
    if isinstance(exc, httpx.NetworkError):
        return "Upstream error: network unreachable"
    return "Upstream error"


def outcome_uncertain(exc: Exception) -> bool:
    return isinstance(exc, (httpx.ReadTimeout, httpx.WriteTimeout, httpx.ReadError,
                            httpx.WriteError, httpx.RemoteProtocolError))


def gateway_failure(message: str) -> dict:
    return {
        "error_origin": "gateway",
        "upstream_status_code": 0,
        "upstream_error": "",
        "error_message": _clip(message),
    }
