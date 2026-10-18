from collections.abc import AsyncIterator

import httpx

from app.models import Channel
from app.providers.base import BaseProvider, forwardable_headers, read_error_body

STREAM_USAGE_ENDPOINTS = {"/v1/chat/completions", "/v1/completions"}


class OpenAIProvider(BaseProvider):
    """Passthrough provider for OpenAI and all OpenAI-compatible APIs
    (OpenAI 官方、第三方中转、Gemini/Qwen 等兼容端点)。"""

    def __init__(self, channel: Channel):
        super().__init__(channel)

    def transform_request(self, openai_request: dict, endpoint: str) -> tuple[str, dict, dict]:
        body = {**openai_request}
        body["model"] = self.apply_model_mapping(body.get("model", ""))
        # The Responses API always reports usage in response.completed and
        # rejects include_usage.
        if body.get("stream") and endpoint in STREAM_USAGE_ENDPOINTS:
            body.setdefault("stream_options", {})["include_usage"] = True
        headers = {"Content-Type": "application/json", **self._auth_headers()}
        return self._path(endpoint), headers, body

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _path(self, endpoint: str) -> str:
        # Allow either a server root or an OpenAI-compatible prefix as Base URL.
        # Examples: http://vllm:8000 and http://vllm:8000/v1.
        path = endpoint.lstrip("/")
        base_path = self.channel.base_url.rstrip("/").lower()
        if base_path.endswith(("/v1", "/v1beta/openai", "/compatible-mode/v1")):
            path = path.removeprefix("v1/")
        return path

    async def send_event_stream(self, body: dict, endpoint: str) -> AsyncIterator[str]:
        """Whole SSE events, keeping the event: line next to its data: line."""
        url_path, headers, payload = self.transform_request(body, endpoint)
        req = self.client.build_request("POST", url_path, json=payload, headers=headers)
        resp = await self.client.send(req, stream=True)
        await read_error_body(resp)
        self.response_headers = forwardable_headers(resp)
        buffer: list[str] = []
        try:
            async for line in resp.aiter_lines():
                if line.strip():
                    buffer.append(line.rstrip("\r"))
                elif buffer:
                    yield "\n".join(buffer) + "\n\n"
                    buffer = []
            if buffer:
                yield "\n".join(buffer) + "\n\n"
        finally:
            await resp.aclose()

    async def send_raw(
        self,
        endpoint: str,
        *,
        json_body: dict | None = None,
        form: dict[str, str] | None = None,
        files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
    ) -> httpx.Response:
        """POST without JSON decoding: binary audio, multipart uploads."""
        if json_body is not None:
            json_body = {**json_body, "model": self.apply_model_mapping(json_body.get("model", ""))}
        if form is not None and "model" in form:
            form = {**form, "model": self.apply_model_mapping(form["model"])}
        resp = await self.client.post(
            self._path(endpoint),
            json=json_body,
            data=form,
            files=files,
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        self.response_headers = forwardable_headers(resp)
        return resp

    async def send_request(self, body: dict, endpoint: str) -> dict:
        url_path, headers, payload = self.transform_request(body, endpoint)
        resp = await self.client.post(url_path, json=payload, headers=headers)
        resp.raise_for_status()
        self.response_headers = forwardable_headers(resp)
        return resp.json()

    async def send_stream(self, body: dict, endpoint: str) -> AsyncIterator[str]:
        url_path, headers, payload = self.transform_request(body, endpoint)
        req = self.client.build_request("POST", url_path, json=payload, headers=headers)
        resp = await self.client.send(req, stream=True)
        await read_error_body(resp)
        self.response_headers = forwardable_headers(resp)
        try:
            async for line in resp.aiter_lines():
                line = line.strip()
                if line:
                    yield f"{line}\n\n"
        finally:
            await resp.aclose()
