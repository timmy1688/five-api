import json
import time
import uuid
from collections.abc import AsyncIterator

import httpx

from app.models import Channel
from app.providers.base import BaseProvider


def _content_to_text(content) -> str:
    """OpenAI 消息 content（字符串或多模态 part 列表）压平成纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            p.get("text", "")
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    if content is None:
        return ""
    return str(content)


def _openai_messages_to_anthropic(messages: list) -> tuple[list[str], list]:
    """OpenAI messages → (system 片段, Anthropic messages)，保留 tool_calls / tool 结果。"""
    system_parts: list[str] = []
    result: list[dict] = []

    for msg in messages:
        role = msg.get("role")

        if role == "system":
            system_parts.append(_content_to_text(msg.get("content")))

        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id", ""),
                "content": _content_to_text(msg.get("content")),
            }
            # 连续的 tool 结果合并进同一个 user 消息，紧跟触发它们的 assistant
            if result and result[-1]["role"] == "user" and isinstance(result[-1]["content"], list):
                result[-1]["content"].append(block)
            else:
                result.append({"role": "user", "content": [block]})

        elif role == "assistant":
            blocks: list[dict] = []
            text = _content_to_text(msg.get("content"))
            if text:
                blocks.append({"type": "text", "text": text})
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except (json.JSONDecodeError, ValueError):
                    args = {}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "input": args,
                })
            if len(blocks) == 1 and blocks[0]["type"] == "text":
                result.append({"role": "assistant", "content": blocks[0]["text"]})
            else:
                result.append({"role": "assistant", "content": blocks or ""})

        else:
            result.append({"role": "user", "content": _content_to_text(msg.get("content"))})

    return system_parts, result


def _convert_openai_tools(tools: list) -> list:
    """OpenAI function tools → Anthropic tools。"""
    out = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        fn = t.get("function") if t.get("type") == "function" else t
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        out.append({
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


def _convert_openai_tool_choice(tc):
    """OpenAI tool_choice → Anthropic tool_choice。"""
    if tc == "auto":
        return {"type": "auto"}
    if tc == "required":
        return {"type": "any"}
    if tc == "none":
        return {"type": "none"}
    if isinstance(tc, dict) and tc.get("type") == "function":
        name = (tc.get("function") or {}).get("name")
        if name:
            return {"type": "tool", "name": name}
    return None


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
        system_parts, messages = _openai_messages_to_anthropic(openai_request.get("messages", []))

        model = self.apply_model_mapping(openai_request.get("model", ""))
        body: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": openai_request.get("max_tokens") or 4096,
        }
        if system_parts:
            body["system"] = "\n".join(p for p in system_parts if p)
        if openai_request.get("temperature") is not None:
            body["temperature"] = min(float(openai_request["temperature"]), 1.0)
        if openai_request.get("top_p") is not None:
            body["top_p"] = openai_request["top_p"]
        if openai_request.get("stop"):
            body["stop_sequences"] = openai_request["stop"] if isinstance(openai_request["stop"], list) else [openai_request["stop"]]
        if openai_request.get("tools"):
            tools = _convert_openai_tools(openai_request["tools"])
            if tools:
                body["tools"] = tools
        if openai_request.get("tool_choice") is not None:
            choice = _convert_openai_tool_choice(openai_request["tool_choice"])
            if choice is not None:
                body["tool_choice"] = choice
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
        tool_calls = []
        for block in provider_response.get("content", []):
            btype = block.get("type")
            if btype == "text":
                content += block.get("text", "")
            elif btype == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {}) or {}, ensure_ascii=False),
                    },
                })

        stop_reason = provider_response.get("stop_reason", "end_turn")
        finish_reason_map = {
            "end_turn": "stop",
            "max_tokens": "length",
            "stop_sequence": "stop",
            "tool_use": "tool_calls",
        }

        usage = provider_response.get("usage", {})
        cache_read = usage.get("cache_read_input_tokens", 0) or 0
        cache_creation = usage.get("cache_creation_input_tokens", 0) or 0
        # Anthropic input_tokens 不含缓存，补齐为 OpenAI 口径（prompt 含全部输入）
        prompt_tokens = (usage.get("input_tokens", 0) or 0) + cache_read + cache_creation
        completion_tokens = usage.get("output_tokens", 0) or 0
        usage_result: dict = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        if cache_read:
            usage_result["prompt_tokens_details"] = {"cached_tokens": cache_read}

        message: dict = {"role": "assistant", "content": content or None}
        if tool_calls:
            message["tool_calls"] = tool_calls

        return {
            "id": f"chatcmpl-{provider_response.get('id', uuid.uuid4().hex[:24])}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": provider_response.get("model", ""),
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason_map.get(stop_reason, "stop"),
                }
            ],
            "usage": usage_result,
        }

    async def stream_transform(self, response: httpx.Response, endpoint: str) -> AsyncIterator[str]:
        chat_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        model = ""
        role_sent = False
        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        cache_creation_tokens = 0
        event_type = ""
        # Anthropic content block index → OpenAI tool_call index
        tool_index_map: dict[int, int] = {}
        next_tool_index = 0

        def _chunk(delta: dict, finish_reason=None, usage=None) -> str:
            choice: dict = {"index": 0, "delta": delta, "finish_reason": finish_reason}
            payload: dict = {
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [choice],
            }
            if usage is not None:
                payload["usage"] = usage
            return f"data: {json.dumps(payload)}\n\n"

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
                cache_creation_tokens = msg_usage.get("cache_creation_input_tokens", 0)

            elif event_type == "content_block_start":
                block = data.get("content_block", {})
                if block.get("type") == "tool_use":
                    anthropic_idx = data.get("index", 0)
                    oai_idx = next_tool_index
                    next_tool_index += 1
                    tool_index_map[anthropic_idx] = oai_idx
                    if not role_sent:
                        yield _chunk({"role": "assistant", "content": ""})
                        role_sent = True
                    yield _chunk({
                        "tool_calls": [{
                            "index": oai_idx,
                            "id": block.get("id", ""),
                            "type": "function",
                            "function": {"name": block.get("name", ""), "arguments": ""},
                        }]
                    })

            elif event_type == "content_block_delta":
                delta = data.get("delta", {})
                dtype = delta.get("type")
                if dtype == "text_delta":
                    if not role_sent:
                        yield _chunk({"role": "assistant", "content": ""})
                        role_sent = True
                    yield _chunk({"content": delta.get("text", "")})
                elif dtype == "input_json_delta":
                    oai_idx = tool_index_map.get(data.get("index", 0), 0)
                    yield _chunk({
                        "tool_calls": [{
                            "index": oai_idx,
                            "function": {"arguments": delta.get("partial_json", "")},
                        }]
                    })

            elif event_type == "message_delta":
                delta = data.get("delta", {})
                output_tokens = data.get("usage", {}).get("output_tokens", 0)
                stop_reason = delta.get("stop_reason", "end_turn")
                finish_map = {
                    "end_turn": "stop",
                    "max_tokens": "length",
                    "stop_sequence": "stop",
                    "tool_use": "tool_calls",
                }
                # Anthropic input_tokens 不含缓存，补齐为 OpenAI 口径（prompt 含全部输入）
                prompt_tokens = input_tokens + cached_tokens + cache_creation_tokens
                usage_data: dict = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": output_tokens,
                    "total_tokens": prompt_tokens + output_tokens,
                }
                if cached_tokens:
                    usage_data["prompt_tokens_details"] = {"cached_tokens": cached_tokens}
                yield _chunk({}, finish_reason=finish_map.get(stop_reason, "stop"), usage=usage_data)

            elif event_type == "message_stop":
                yield "data: [DONE]\n\n"
