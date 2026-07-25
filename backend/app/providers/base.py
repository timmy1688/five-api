from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx

from app.models import Channel
from app.utils.secrets import decrypt_secret

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


async def close_http_clients() -> None:
    clients = list(_http_clients.values())
    _http_clients.clear()
    for client in clients:
        await client.aclose()


class BaseProvider(ABC):
    def __init__(self, channel: Channel):
        self.channel = channel
        self.api_key = decrypt_secret(channel.api_key)
        self.client = _shared_http_client(channel)

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
        return self.channel.model_mapping.get(model, model)

    async def send_request(self, openai_request: dict, endpoint: str) -> dict:
        url_path, headers, body = self.transform_request(openai_request, endpoint)
        resp = await self.client.post(url_path, json=body, headers=headers)
        resp.raise_for_status()
        return self.transform_response(resp.json(), endpoint)

    async def send_stream(self, openai_request: dict, endpoint: str) -> AsyncIterator[str]:
        url_path, headers, body = self.transform_request(openai_request, endpoint)
        req = self.client.build_request("POST", url_path, json=body, headers=headers)
        resp = await self.client.send(req, stream=True)
        resp.raise_for_status()
        try:
            async for line in self.stream_transform(resp, endpoint):
                yield line
        finally:
            await resp.aclose()

    async def close(self):
        # Clients are shared per upstream and closed during application shutdown.
        return None
