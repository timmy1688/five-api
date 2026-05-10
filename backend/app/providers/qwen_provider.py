from collections.abc import AsyncIterator

import httpx

from app.models import Channel
from app.providers.base import BaseProvider


class QwenProvider(BaseProvider):
    """Alibaba Qwen/DashScope via its OpenAI-compatible endpoint — passthrough."""

    def __init__(self, channel: Channel):
        super().__init__(channel)

    def transform_request(self, openai_request: dict, endpoint: str) -> tuple[str, dict, dict]:
        body = {**openai_request}
        body["model"] = self.apply_model_mapping(body.get("model", ""))
        if body.get("stream"):
            body.setdefault("stream_options", {})["include_usage"] = True
        headers = {
            "Authorization": f"Bearer {self.channel.api_key}",
            "Content-Type": "application/json",
        }
        return endpoint, headers, body

    def transform_response(self, provider_response: dict, endpoint: str) -> dict:
        return provider_response

    async def stream_transform(self, response: httpx.Response, endpoint: str) -> AsyncIterator[str]:
        async for line in response.aiter_lines():
            line = line.strip()
            if line:
                yield f"{line}\n\n"
