from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx

from app.models import Channel
from app.utils.secrets import channel_keys

_http_clients: dict[tuple[str, int], httpx.AsyncClient] = {}


def _shared_http_client(channel: Channel) -> httpx.AsyncClient:
    base_url = channel.base_url.rstrip("/")
    key = (base_url, channel.timeout)
    client = _http_clients.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(float(channel.timeout), connect=10.0),
            limits=httpx.Limits(
                max_connections=200,
                max_keepalive_connections=50,
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


async def read_error_body(resp: httpx.Response) -> None:
    """Load an error body before raising, so the client can receive the upstream JSON."""
    if resp.status_code < 400:
        return
    try:
        await resp.aread()
    except Exception:
        pass
    try:
        resp.raise_for_status()
    finally:
        await resp.aclose()


async def close_http_clients() -> None:
    clients = list(_http_clients.values())
    _http_clients.clear()
    for client in clients:
        await client.aclose()


class BaseProvider(ABC):
    def __init__(self, channel: Channel):
        self.channel = channel
        # Set when this channel serves a fallback model instead of the requested one.
        self.model_override: str | None = None
        self.keys = channel_keys(channel.api_key)
        self.api_key = self.keys[0] if self.keys else ""
        self.client = _shared_http_client(channel)
        self.response_headers: dict[str, str] = {}

    async def select_key(self, session_key: str | None = None) -> None:
        from app.services.key_pool import pick_key

        if len(self.keys) > 1:
            self.api_key = await pick_key(self.channel.id, self.keys, session_key)

    async def rotate_key(self, exc: Exception) -> bool:
        """Cool the failing key. True when another key on this channel is ready."""
        from app.services.key_pool import available_keys, cool_down, cooldown_for

        if len(self.keys) <= 1:
            return False
        await cool_down(self.channel.id, self.api_key, cooldown_for(exc))
        ready = [key for key in await available_keys(self.channel.id, self.keys) if key != self.api_key]
        if not ready:
            return False
        self.api_key = ready[0]
        return True

    @abstractmethod
    def transform_request(self, openai_request: dict, endpoint: str) -> tuple[str, dict, dict]:
        """Convert OpenAI-format request to provider format. Returns (url_path, headers, body)."""

    @abstractmethod
    def transform_response(self, provider_response: dict, endpoint: str) -> dict:
        """Convert provider response to OpenAI format."""

    @abstractmethod
    async def stream_transform(self, response: httpx.Response, endpoint: str) -> AsyncIterator[str]:
        """Yield OpenAI-format SSE lines from provider stream."""

    def apply_model_mapping(self, model: str) -> str:
        model = self.model_override or model
        return self.channel.model_mapping.get(model, model)

    async def send_request(self, openai_request: dict, endpoint: str) -> dict:
        url_path, headers, body = self.transform_request(openai_request, endpoint)
        resp = await self.client.post(url_path, json=body, headers=headers)
        resp.raise_for_status()
        self.response_headers = forwardable_headers(resp)
        return self.transform_response(resp.json(), endpoint)

    async def send_stream(self, openai_request: dict, endpoint: str) -> AsyncIterator[str]:
        url_path, headers, body = self.transform_request(openai_request, endpoint)
        req = self.client.build_request("POST", url_path, json=body, headers=headers)
        resp = await self.client.send(req, stream=True)
        await read_error_body(resp)
        self.response_headers = forwardable_headers(resp)
        try:
            async for line in self.stream_transform(resp, endpoint):
                yield line
        finally:
            await resp.aclose()

    async def close(self):
        # Clients are shared per upstream and closed during application shutdown.
        return None
