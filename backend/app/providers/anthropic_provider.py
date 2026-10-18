from collections.abc import AsyncIterator

from app.models import Channel
from app.providers.base import BaseProvider, forwardable_headers, read_error_body


class AnthropicProvider(BaseProvider):
    def __init__(self, channel: Channel):
        super().__init__(channel)

    # ── Anthropic native pass-through (used by /v1/messages when upstream is anthropic) ──

    def _path(self, resource: str) -> str:
        # Base URL may be the server root or already end in /v1.
        if self.channel.base_url.rstrip("/").lower().endswith("/v1"):
            return f"/{resource}"
        return f"/v1/{resource}"

    def _anthropic_headers(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        if extra_headers:
            # 客户端要哪个 beta 就交给上游。白名单会把 Claude Code 的新名字删掉，
            # 请求仍可能成功，只是对应能力没了。上游不认识时由上游返回 400。
            beta = ", ".join(
                part.strip()
                for part in extra_headers.get("anthropic-beta", "").split(",")
                if part.strip()
            )
            if beta:
                headers["anthropic-beta"] = beta
            direct = extra_headers.get("anthropic-dangerous-direct-browser-access")
            if direct:
                headers["anthropic-dangerous-direct-browser-access"] = direct
        return headers

    async def send_anthropic_passthrough(
        self, body: dict, extra_headers: dict[str, str] | None = None,
    ) -> dict:
        body = {**body, "model": self.apply_model_mapping(body.get("model", ""))}
        body.pop("stream", None)
        headers = self._anthropic_headers(extra_headers)
        resp = await self.client.post(self._path("messages"), json=body, headers=headers)
        resp.raise_for_status()
        self.response_headers = forwardable_headers(resp)
        return resp.json()

    async def count_tokens(
        self, body: dict, extra_headers: dict[str, str] | None = None,
    ) -> dict:
        body = {**body, "model": self.apply_model_mapping(body.get("model", ""))}
        body.pop("stream", None)
        body.pop("max_tokens", None)
        headers = self._anthropic_headers(extra_headers)
        resp = await self.client.post(
            self._path("messages/count_tokens"), json=body, headers=headers,
        )
        resp.raise_for_status()
        self.response_headers = forwardable_headers(resp)
        return resp.json()

    async def stream_anthropic_passthrough(
        self, body: dict, extra_headers: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        body = {**body, "model": self.apply_model_mapping(body.get("model", "")), "stream": True}
        headers = self._anthropic_headers(extra_headers)
        req = self.client.build_request("POST", self._path("messages"), json=body, headers=headers)
        resp = await self.client.send(req, stream=True)
        await read_error_body(resp)
        self.response_headers = forwardable_headers(resp)
        try:
            async for raw_line in resp.aiter_lines():
                line = raw_line.strip()
                if line:
                    yield f"{line}\n"
                else:
                    yield "\n"
        finally:
            await resp.aclose()
