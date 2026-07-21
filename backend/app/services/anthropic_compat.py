import json
import uuid
from collections.abc import AsyncIterator

# ── Anthropic → OpenAI helpers ──


def _blocks_to_text(content) -> str:
    """把 Anthropic 的 content（字符串或 block 列表）压平成纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _tool_result_content_to_text(content) -> str:
    """tool_result 的 content 可能是字符串或 block 列表，取其文本表示。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
        if parts:
            return "".join(parts)
        return json.dumps(content, ensure_ascii=False)
    return json.dumps(content, ensure_ascii=False)


def _convert_anthropic_tools(tools: list) -> list:
    """Anthropic tools → OpenAI function tools。"""
    out = []
    for t in tools:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            },
        })
    return out


def _convert_anthropic_tool_choice(tc):
    """Anthropic tool_choice → OpenAI tool_choice。"""
    if not isinstance(tc, dict):
        return None
    t = tc.get("type")
    if t == "auto":
        return "auto"
    if t == "any":
        return "required"
    if t == "none":
        return "none"
    if t == "tool" and tc.get("name"):
        return {"type": "function", "function": {"name": tc["name"]}}
    return None


def _convert_anthropic_messages(messages: list) -> list:
    """Anthropic messages → OpenAI messages，保留 tool_use / tool_result。"""
    result: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if isinstance(content, str):
            result.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            result.append({"role": role, "content": ""})
            continue

        if role == "assistant":
            text_parts = []
            tool_calls = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    tool_calls.append({
                        "id": block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input", {}) or {}, ensure_ascii=False),
                        },
                    })
            asst: dict = {"role": "assistant", "content": "".join(text_parts) or None}
            if tool_calls:
                asst["tool_calls"] = tool_calls
            result.append(asst)
        else:
            # user（或其它）：tool_result → 独立的 tool 消息，紧跟在触发它的 assistant 之后
            text_parts = []
            tool_results = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_result":
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": _tool_result_content_to_text(block.get("content")),
                    })
            result.extend(tool_results)
            if text_parts:
                result.append({"role": "user", "content": "".join(text_parts)})
    return result


def anthropic_to_openai_request(body: dict) -> dict:
    messages = []

    system = body.get("system")
    if system:
        text = _blocks_to_text(system) if isinstance(system, list) else system
        if text:
            messages.append({"role": "system", "content": text})

    messages.extend(_convert_anthropic_messages(body.get("messages", [])))

    result: dict = {"model": body["model"], "messages": messages}

    if body.get("max_tokens") is not None:
        result["max_tokens"] = body["max_tokens"]
    if body.get("temperature") is not None:
        result["temperature"] = body["temperature"]
    if body.get("top_p") is not None:
        result["top_p"] = body["top_p"]
    if body.get("stop_sequences"):
        result["stop"] = body["stop_sequences"]
    if body.get("tools"):
        tools = _convert_anthropic_tools(body["tools"])
        if tools:
            result["tools"] = tools
    if body.get("tool_choice"):
        choice = _convert_anthropic_tool_choice(body["tool_choice"])
        if choice is not None:
            result["tool_choice"] = choice
    if body.get("stream"):
        result["stream"] = True
        # 让 OpenAI 兼容上游在流末回吐 usage，否则计费/日志拿不到 token 数
        result["stream_options"] = {"include_usage": True}

    return result


# ── OpenAI → Anthropic helpers ──

_STOP_REASON_MAP = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}


def openai_to_anthropic_response(openai_resp: dict, model: str) -> dict:
    choice = openai_resp.get("choices", [{}])[0]
    message = choice.get("message", {})

    content_blocks: list[dict] = []
    text = message.get("content") or ""
    if text:
        content_blocks.append({"type": "text", "text": text})

    for tc in message.get("tool_calls") or []:
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except (json.JSONDecodeError, ValueError):
            args = {}
        content_blocks.append({
            "type": "tool_use",
            "id": tc.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
            "name": fn.get("name", ""),
            "input": args,
        })

    if not content_blocks:
        content_blocks.append({"type": "text", "text": ""})

    finish_reason = choice.get("finish_reason", "stop")

    usage = openai_resp.get("usage", {})
    anthropic_usage: dict = {
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }
    cache_read = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    if cache_read:
        anthropic_usage["cache_read_input_tokens"] = cache_read

    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content_blocks,
        "stop_reason": _STOP_REASON_MAP.get(finish_reason, "end_turn"),
        "stop_sequence": None,
        "usage": anthropic_usage,
    }


async def openai_stream_to_anthropic_stream(
    openai_sse_iterator: AsyncIterator[str],
    model: str,
) -> AsyncIterator[tuple[str, dict]]:
    """OpenAI Chat 流 → Anthropic Messages 流。

    每次 yield ``(anthropic_sse_line, usage_dict)``，usage 为累计值（OpenAI 口径：
    prompt_tokens / completion_tokens / cached_tokens），供上层计费与日志使用。

    文本 delta 实时透传（content block 0）；tool_calls 分片按 index 累积，
    在流结束时统一以 tool_use block 输出（避免并行工具调用时分片交错导致的乱序）。
    """
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"
    next_index = 0
    text_index: int | None = None
    text_started = False
    stop_reason = "end_turn"
    input_tokens = 0
    output_tokens = 0
    cached_tokens = 0
    tool_calls: dict[int, dict] = {}
    tool_order: list[int] = []

    def _usage() -> dict:
        return {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "cached_tokens": cached_tokens,
        }

    message_start = {
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    }
    yield f"event: message_start\ndata: {json.dumps(message_start)}\n\n", _usage()

    async for line in openai_sse_iterator:
        line = line.strip()
        if not line or line == "data: [DONE]" or not line.startswith("data: "):
            continue

        try:
            chunk = json.loads(line[6:])
        except (json.JSONDecodeError, ValueError):
            continue

        usage = chunk.get("usage")
        if usage:
            input_tokens = usage.get("prompt_tokens", input_tokens)
            output_tokens = usage.get("completion_tokens", output_tokens)
            cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", cached_tokens)

        choices = chunk.get("choices", [])
        if not choices:
            continue

        delta = choices[0].get("delta", {})
        finish_reason = choices[0].get("finish_reason")

        text = delta.get("content")
        if text:
            if not text_started:
                text_index = next_index
                next_index += 1
                block_start = {
                    "type": "content_block_start",
                    "index": text_index,
                    "content_block": {"type": "text", "text": ""},
                }
                yield f"event: content_block_start\ndata: {json.dumps(block_start)}\n\n", _usage()
                text_started = True

            block_delta = {
                "type": "content_block_delta",
                "index": text_index,
                "delta": {"type": "text_delta", "text": text},
            }
            yield f"event: content_block_delta\ndata: {json.dumps(block_delta)}\n\n", _usage()

        for tc in delta.get("tool_calls") or []:
            oai_idx = tc.get("index", 0)
            if oai_idx not in tool_calls:
                tool_calls[oai_idx] = {"id": "", "name": "", "args": ""}
                tool_order.append(oai_idx)
            fn = tc.get("function") or {}
            if tc.get("id"):
                tool_calls[oai_idx]["id"] = tc["id"]
            if fn.get("name"):
                tool_calls[oai_idx]["name"] = fn["name"]
            if fn.get("arguments"):
                tool_calls[oai_idx]["args"] += fn["arguments"]

        if finish_reason is not None:
            stop_reason = _STOP_REASON_MAP.get(finish_reason, "end_turn")

    if text_started:
        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': text_index})}\n\n", _usage()

    for oai_idx in tool_order:
        tc = tool_calls[oai_idx]
        idx = next_index
        next_index += 1
        block_start = {
            "type": "content_block_start",
            "index": idx,
            "content_block": {
                "type": "tool_use",
                "id": tc["id"] or f"toolu_{uuid.uuid4().hex[:24]}",
                "name": tc["name"],
                "input": {},
            },
        }
        yield f"event: content_block_start\ndata: {json.dumps(block_start)}\n\n", _usage()
        if tc["args"]:
            block_delta = {
                "type": "content_block_delta",
                "index": idx,
                "delta": {"type": "input_json_delta", "partial_json": tc["args"]},
            }
            yield f"event: content_block_delta\ndata: {json.dumps(block_delta)}\n\n", _usage()
        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': idx})}\n\n", _usage()

    if tool_order and stop_reason == "end_turn":
        stop_reason = "tool_use"

    delta_usage: dict = {"output_tokens": output_tokens}
    if cached_tokens:
        delta_usage["cache_read_input_tokens"] = cached_tokens
    msg_delta = {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": delta_usage,
    }
    yield f"event: message_delta\ndata: {json.dumps(msg_delta)}\n\n", _usage()
    yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n", _usage()
