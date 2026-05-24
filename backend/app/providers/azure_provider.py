from collections.abc import AsyncIterator

import httpx

from app.models import Channel
from app.providers.base import BaseProvider


class AzureProvider(BaseProvider):
    """Azure OpenAI — different URL pattern and api-key header auth."""

    def __init__(self, channel: Channel):
        super().__init__(channel)
        self.api_version = "2024-12-01-preview"

    def transform_request(self, openai_request: dict, endpoint: str) -> tuple[str, dict, dict]:
        body = {**openai_request}
        model = self.apply_model_mapping(body.pop("model", ""))
        if body.get("stream"):
            body.setdefault("stream_options", {})["include_usage"] = True
        headers = {
            "api-key": self.channel.api_key,
            "Content-Type": "application/json",
        }
        # Azure URL: /openai/deployments/{model}/chat/completions?api-version=...
        url_path = f"/openai/deployments/{model}{endpoint}?api-version={self.api_version}"
        return url_path, headers, body

    def transform_response(self, provider_response: dict, endpoint: str) -> dict:
        return provider_response

    async def stream_transform(self, response: httpx.Response, endpoint: str) -> AsyncIterator[str]:
        async for line in response.aiter_lines():
            line = line.strip()
            if line:
                yield f"{line}\n\n"
