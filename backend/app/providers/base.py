from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx

from app.models import Channel


class BaseProvider(ABC):
    def __init__(self, channel: Channel):
        self.channel = channel
        self.client = httpx.AsyncClient(
            base_url=channel.base_url.rstrip("/"),
            timeout=httpx.Timeout(float(channel.timeout), connect=10.0),
        )

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
        await self.client.aclose()
