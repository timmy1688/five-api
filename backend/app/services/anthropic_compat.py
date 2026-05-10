import json
import uuid
from collections.abc import AsyncIterator


def anthropic_to_openai_request(body: dict) -> dict:
    messages = []

    system = body.get("system")
    if system:
        if isinstance(system, list):
            text = "\n".join(
                block.get("text", "")
                for block in system
                if isinstance(block, dict) and block.get("type") == "text"
            )
        else:
            text = system
        if text:
            messages.append({"role": "system", "content": text})

    for msg in body.get("messages", []):
        messages.append({"role": msg["role"], "content": msg.get("content", "")})

    result = {"model": body["model"], "messages": messages}

    if body.get("max_tokens") is not None:
        result["max_tokens"] = body["max_tokens"]
    if body.get("temperature") is not None:
        result["temperature"] = body["temperature"]
    if body.get("top_p") is not None:
        result["top_p"] = body["top_p"]
    if body.get("stop_sequences"):
        result["stop"] = body["stop_sequences"]
    if body.get("stream"):
        result["stream"] = True

    return result


def openai_to_anthropic_response(openai_resp: dict, model: str) -> dict:
    choice = openai_resp.get("choices", [{}])[0]
    message = choice.get("message", {})
    content_text = message.get("content", "") or ""

    finish_reason = choice.get("finish_reason", "stop")
    stop_reason_map = {"stop": "end_turn", "length": "max_tokens"}

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
        "content": [{"type": "text", "text": content_text}],
        "stop_reason": stop_reason_map.get(finish_reason, "end_turn"),
        "stop_sequence": None,
        "usage": anthropic_usage,
    }


async def openai_stream_to_anthropic_stream(
    openai_sse_iterator: AsyncIterator[str],
    model: str,
) -> AsyncIterator[str]:
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"
    content_block_started = False
    stop_reason = "end_turn"
    input_tokens = 0
    output_tokens = 0
    cached_tokens = 0

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
    yield f"event: message_start\ndata: {json.dumps(message_start)}\n\n"

    async for line in openai_sse_iterator:
        line = line.strip()
        if not line or line == "data: [DONE]":
            continue
        if not line.startswith("data: "):
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
        if text is not None:
            if not content_block_started:
                block_start = {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                }
                yield f"event: content_block_start\ndata: {json.dumps(block_start)}\n\n"
                content_block_started = True

            if text:
                block_delta = {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": text},
                }
                yield f"event: content_block_delta\ndata: {json.dumps(block_delta)}\n\n"

        if finish_reason is not None:
            stop_reason = {"stop": "end_turn", "length": "max_tokens"}.get(
                finish_reason, "end_turn"
            )

    if content_block_started:
        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"

    delta_usage: dict = {"output_tokens": output_tokens}
    if cached_tokens:
        delta_usage["cache_read_input_tokens"] = cached_tokens
    msg_delta = {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": delta_usage,
    }
    yield f"event: message_delta\ndata: {json.dumps(msg_delta)}\n\n"
    yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"
