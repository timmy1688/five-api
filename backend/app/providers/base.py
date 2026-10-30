import httpx

from app.models import Channel
from app.services.key_pool import available_keys, cool_down, cooldown_for, pick_key
from app.utils.secrets import channel_keys

_http_clients: dict[tuple[str, int], httpx.AsyncClient] = {}


def _shared_http_client(channel: Channel) -> httpx.AsyncClient:
    from app.utils.upstream_security import validate_upstream_base_url
    base_url = validate_upstream_base_url(channel.base_url)
    key = (base_url, channel.timeout)
    client = _http_clients.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(float(channel.timeout), connect=10.0),
            # Streams hold a connection for their whole duration, so the cap bounds concurrent calls per upstream.
            limits=httpx.Limits(
                max_connections=1000,
                max_keepalive_connections=200,
                keepalive_expiry=30,
            ),
        )
        _http_clients[key] = client
    return client


_FORWARD_PREFIXES = ("x-ratelimit-", "anthropic-ratelimit-")
_FORWARD_NAMES = {"retry-after", "retry-after-ms", "request-id"}


def forwardable_headers(resp: httpx.Response) -> dict[str, str]:
    """Upstream headers the client SDK reads for backoff and support tickets.

    The upstream x-request-id becomes x-upstream-request-id, because the gateway
    sets its own X-Request-ID for log lookup.
    """
    out: dict[str, str] = {}
    headers = getattr(resp, "headers", None)
    if not isinstance(headers, (httpx.Headers, dict)):
        return out
    for name, value in headers.items():
        lower = name.lower()
        if lower.startswith(_FORWARD_PREFIXES) or lower in _FORWARD_NAMES:
            out[lower] = value
        elif lower == "x-request-id":
            out["x-upstream-request-id"] = value
    return out


# Relays such as New API answer some failures with HTTP 200 and an error body.
# Client mistakes keep a 4xx so they neither fail over nor trip the breaker.
_ERROR_TYPE_STATUS = {
    "invalid_request_error": 400,
    "authentication_error": 401,
    "permission_error": 403,
    "not_found_error": 404,
    "rate_limit_error": 429,
}
_ERROR_ONLY_KEYS = {"error", "type", "request_id"}
ERROR_IN_OK = "five_error_in_ok"


def raise_for_error_body(resp: httpx.Response) -> None:
    """raise_for_status, plus a 2xx whose JSON body is only an error object."""
    resp.raise_for_status()
    headers = getattr(resp, "headers", None)
    if not isinstance(headers, (httpx.Headers, dict)) or "json" not in headers.get("content-type", ""):
        return
    try:
        data = resp.json()
    except ValueError:
        return
    if not isinstance(data, dict) or not isinstance(data.get("error"), dict) or set(data) - _ERROR_ONLY_KEYS:
        return
    status = _ERROR_TYPE_STATUS.get(str(data["error"].get("type") or ""), 502)
    failed = httpx.Response(
        status, content=resp.content, headers=resp.headers, request=resp.request,
        extensions={ERROR_IN_OK: True},
    )
    raise httpx.HTTPStatusError(f"Upstream error in HTTP {resp.status_code} body", request=resp.request, response=failed)


async def read_error_body(resp: httpx.Response) -> None:
    """Load an error body before raising, so the client can receive the upstream JSON.

    A stream answered with JSON instead of events is read the same way.
    """
    if resp.status_code < 400 and "json" not in resp.headers.get("content-type", ""):
        return
    try:
        await resp.aread()
    except Exception:
        pass
    try:
        raise_for_error_body(resp)
    except Exception:
        await resp.aclose()
        raise


async def close_http_clients() -> None:
    clients = list(_http_clients.values())
    _http_clients.clear()
    for client in clients:
        await client.aclose()


class BaseProvider:
    def __init__(self, channel: Channel):
        self.channel = channel
        # Set when this channel serves a fallback model instead of the requested one.
        self.model_override: str | None = None
        self.keys = channel_keys(channel.api_key)
        from app.services.request_context import remember_credential
        for key in self.keys:
            remember_credential(key)
        self.api_key = self.keys[0] if self.keys else ""
        self.client = _shared_http_client(channel)
        self.response_headers: dict[str, str] = {}

    async def has_ready_key(self) -> bool:
        return len(self.keys) <= 1 or bool(await available_keys(self.channel.id, self.keys))

    async def select_key(self, session_key: str | None = None) -> None:
        if len(self.keys) > 1:
            self.api_key = await pick_key(self.channel.id, self.keys, session_key)

    async def rotate_key(self, exc: Exception) -> bool:
        """Cool the failing key. True when another key on this channel is ready."""
        if len(self.keys) <= 1:
            return False
        await cool_down(self.channel.id, self.api_key, cooldown_for(exc))
        ready = [key for key in await available_keys(self.channel.id, self.keys) if key != self.api_key]
        if not ready:
            return False
        self.api_key = ready[0]
        return True

    def apply_model_mapping(self, model: str) -> str:
        model = self.model_override or model
        return self.channel.model_mapping.get(model, model)

    async def close(self):
        # Clients are shared per upstream and closed during application shutdown.
        return None
