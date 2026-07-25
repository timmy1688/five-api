from collections.abc import AsyncIterator

import httpx

from app.models import Channel
from app.providers.base import BaseProvider


class OpenAIProvider(BaseProvider):
    """Passthrough provider for OpenAI and all OpenAI-compatible APIs
    (OpenAI 官方、第三方中转、Gemini/Qwen 等兼容端点)。"""

    def __init__(self, channel: Channel):
        super().__init__(channel)

    def transform_request(self, openai_request: dict, endpoint: str) -> tuple[str, dict, dict]:
        body = {**openai_request}
        body["model"] = self.apply_model_mapping(body.get("model", ""))
        if body.get("stream"):
            body.setdefault("stream_options", {})["include_usage"] = True
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # Allow either a server root or an OpenAI-compatible prefix as Base URL.
        # Examples: http://vllm:8000 and http://vllm:8000/v1.
        path = endpoint.lstrip("/")
        base_path = self.channel.base_url.rstrip("/").lower()
        if base_path.endswith(("/v1", "/v1beta/openai", "/compatible-mode/v1")):
            path = path.removeprefix("v1/")
        return path, headers, body

    def transform_response(self, provider_response: dict, endpoint: str) -> dict:
        return provider_response

    async def stream_transform(self, response: httpx.Response, endpoint: str) -> AsyncIterator[str]:
        async for line in response.aiter_lines():
            line = line.strip()
            if line:
                yield f"{line}\n\n"
