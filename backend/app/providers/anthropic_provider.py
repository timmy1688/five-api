import json
import time
import uuid
from collections.abc import AsyncIterator

import httpx

from app.models import Channel
from app.providers.base import BaseProvider


class AnthropicProvider(BaseProvider):
    def __init__(self, channel: Channel):
        super().__init__(channel)

    # ── Anthropic native pass-through (used by /v1/messages when upstream is anthropic) ──

    SUPPORTED_BETAS = {
        "messages-2023-12-15",
        "max-tokens-3-5-sonnet-2024-07-15",
        "prompt-caching-2024-07-31",
        "token-counting-2024-11-01",
        "extended-cache-ttl-2024-12-19",
        "output-128k-2025-02-19",
        "interleaved-thinking-2025-05-14",
    }

    def _anthropic_headers(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "x-api-key": self.channel.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        if extra_headers:
            if "anthropic-beta" in extra_headers:
                betas = [
                    b.strip() for b in extra_headers["anthropic-beta"].split(",")
                    if b.strip() in self.SUPPORTED_BETAS
                ]
                if betas:
                    headers["anthropic-beta"] = ", ".join(betas)
            if "anthropic-dangerous-direct-browser-access" in extra_headers:
                headers["anthropic-dangerous-direct-browser-access"] = extra_headers["anthropic-dangerous-direct-browser-access"]
        return headers

    async def send_anthropic_passthrough(
        self, body: dict, extra_headers: dict[str, str] | None = None,
    ) -> dict:
        body = {**body, "model": self.apply_model_mapping(body.get("model", ""))}
        body.pop("stream", None)
        headers = self._anthropic_headers(extra_headers)
        resp = await self.client.post("/v1/messages", json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def stream_anthropic_passthrough(
        self, body: dict, extra_headers: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        body = {**body, "model": self.apply_model_mapping(body.get("model", "")), "stream": True}
        headers = self._anthropic_headers(extra_headers)
        req = self.client.build_request("POST", "/v1/messages", json=body, headers=headers)
        resp = await self.client.send(req, stream=True)
        resp.raise_for_status()
        try:
            async for raw_line in resp.aiter_lines():
                line = raw_line.strip()
                if line:
                    yield f"{line}\n"
                else:
                    yield "\n"
        finally:
            await resp.aclose()

    def transform_request(self, openai_request: dict, endpoint: str) -> tuple[str, dict, dict]:
        messages = openai_request.get("messages", [])
        system_parts = []
        filtered_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = "".join(
                        part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
                    )
                system_parts.append(content)
            else:
                filtered_messages.append({"role": msg["role"], "content": msg.get("content") or ""})

        model = self.apply_model_mapping(openai_request.get("model", ""))
        body: dict = {
            "model": model,
            "messages": filtered_messages,
            "max_tokens": openai_request.get("max_tokens") or 4096,
        }
        if system_parts:
            body["system"] = "\n".join(system_parts)
        if openai_request.get("temperature") is not None:
            body["temperature"] = min(float(openai_request["temperature"]), 1.0)
        if openai_request.get("top_p") is not None:
            body["top_p"] = openai_request["top_p"]
        if openai_request.get("stop"):
            body["stop_sequences"] = openai_request["stop"] if isinstance(openai_request["stop"], list) else [openai_request["stop"]]
        if openai_request.get("stream"):
            body["stream"] = True

        headers = {
            "x-api-key": self.channel.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        return "/v1/messages", headers, body

    def transform_response(self, provider_response: dict, endpoint: str) -> dict:
        content = ""
        for block in provider_response.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")

        stop_reason = provider_response.get("stop_reason", "end_turn")
        finish_reason_map = {"end_turn": "stop", "max_tokens": "length", "stop_sequence": "stop"}

        usage = provider_response.get("usage", {})
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)
        usage_result: dict = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        cache_read = usage.get("cache_read_input_tokens", 0)
        if cache_read:
            usage_result["prompt_tokens_details"] = {"cached_tokens": cache_read}

        return {
            "id": f"chatcmpl-{provider_response.get('id', uuid.uuid4().hex[:24])}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": provider_response.get("model", ""),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason_map.get(stop_reason, "stop"),
                }
            ],
            "usage": usage_result,
        }

    async def stream_transform(self, response: httpx.Response, endpoint: str) -> AsyncIterator[str]:
        chat_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        model = ""
        first_content = True
        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        event_type = ""

        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("event:"):
                event_type = line[6:].strip()
                continue

            if not line.startswith("data:"):
                continue

            data_str = line[5:].strip()
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if event_type == "message_start":
                msg = data.get("message", {})
                model = msg.get("model", "")
                msg_usage = msg.get("usage", {})
                input_tokens = msg_usage.get("input_tokens", 0)
                cached_tokens = msg_usage.get("cache_read_input_tokens", 0)

            elif event_type == "content_block_delta":
                delta = data.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if first_content:
                        chunk = {
                            "id": chat_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model,
                            "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"
                        first_content = False
                    chunk = {
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"

            elif event_type == "message_delta":
                delta = data.get("delta", {})
                output_tokens = data.get("usage", {}).get("output_tokens", 0)
                stop_reason = delta.get("stop_reason", "end_turn")
                finish_map = {"end_turn": "stop", "max_tokens": "length", "stop_sequence": "stop"}
                usage_data: dict = {
                        "prompt_tokens": input_tokens,
                        "completion_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens,
                    }
                if cached_tokens:
                    usage_data["prompt_tokens_details"] = {"cached_tokens": cached_tokens}
                chunk = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": finish_map.get(stop_reason, "stop")}],
                    "usage": usage_data,
                }
                yield f"data: {json.dumps(chunk)}\n\n"

            elif event_type == "message_stop":
                yield "data: [DONE]\n\n"
