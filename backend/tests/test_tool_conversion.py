import json

import httpx
import pytest

from app.models import Channel
from app.providers.anthropic_provider import AnthropicProvider
from app.services.anthropic_compat import (
    anthropic_to_openai_request,
    openai_stream_to_anthropic_stream,
    openai_to_anthropic_response,
)

pytestmark = pytest.mark.asyncio


async def _lines(items: list[str]):
    for item in items:
        yield item


def _sse_data(line: str) -> dict | None:
    for part in line.splitlines():
        if part.startswith("data: ") and part != "data: [DONE]":
            return json.loads(part[6:])
    return None


def _function_tool(name: str) -> dict:
    return {
        "name": name,
        "description": f"Run {name}",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    }


async def test_anthropic_request_to_openai_preserves_parallel_tool_round_trip():
    result = anthropic_to_openai_request({
        "model": "gateway-model",
        "system": [
            {"type": "text", "text": "Be concise. "},
            {"type": "text", "text": "Use tools."},
        ],
        "messages": [
            {"role": "user", "content": "Compare Beijing and Shanghai weather"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Checking both."},
                    {
                        "type": "tool_use",
                        "id": "toolu_beijing",
                        "name": "weather",
                        "input": {"city": "北京"},
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_shanghai",
                        "name": "weather",
                        "input": {"city": "上海"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_beijing",
                        "content": [{"type": "text", "text": "18°C"}],
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_shanghai",
                        "content": "24°C",
                    },
                    {"type": "text", "text": "Summarize."},
                ],
            },
        ],
        "tools": [_function_tool("weather")],
        "tool_choice": {"type": "any", "disable_parallel_tool_use": True},
        "thinking": {"type": "disabled"},
        "stream": True,
    })

    assert result["messages"][0] == {
        "role": "system",
        "content": "Be concise. Use tools.",
    }
    assistant = result["messages"][2]
    assert assistant["content"] == "Checking both."
    assert [call["id"] for call in assistant["tool_calls"]] == [
        "toolu_beijing",
        "toolu_shanghai",
    ]
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {
        "city": "北京"
    }
    assert result["messages"][3:6] == [
        {"role": "tool", "tool_call_id": "toolu_beijing", "content": "18°C"},
        {"role": "tool", "tool_call_id": "toolu_shanghai", "content": "24°C"},
        {"role": "user", "content": "Summarize."},
    ]
    assert result["tools"][0]["function"]["parameters"]["required"] == ["city"]
    assert result["tool_choice"] == "required"
    assert result["parallel_tool_calls"] is False
    assert result["thinking"] == {"type": "disabled"}
    assert result["stream_options"] == {"include_usage": True}


async def test_openai_request_to_anthropic_preserves_tools_and_results():
    channel = await Channel.create(
        name="anthropic-tool-conversion",
        provider="anthropic",
        base_url="https://api.anthropic.test",
        api_key="sk-test",
        models=["gateway-model"],
        model_mapping={"gateway-model": "claude-upstream"},
    )
    provider = AnthropicProvider(channel)
    _, headers, body = provider.transform_request({
        "model": "gateway-model",
        "messages": [
            {"role": "system", "content": "Use the tools."},
            {"role": "user", "content": "Compare two cities"},
            {
                "role": "assistant",
                "content": "Checking.",
                "tool_calls": [
                    {
                        "id": "call_a",
                        "type": "function",
                        "function": {
                            "name": "weather",
                            "arguments": '{"city":"北京"}',
                        },
                    },
                    {
                        "id": "call_b",
                        "type": "function",
                        "function": {
                            "name": "weather",
                            "arguments": '{"city":"上海"}',
                        },
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "call_a", "content": "18°C"},
            {"role": "tool", "tool_call_id": "call_b", "content": "24°C"},
            {"role": "user", "content": "Summarize."},
        ],
        "tools": [{
            "type": "function",
            "function": {
                "name": "weather",
                "description": "Get weather",
                "parameters": {"type": "object", "properties": {}},
            },
        }],
        "tool_choice": {
            "type": "function",
            "function": {"name": "weather"},
        },
        "parallel_tool_calls": False,
    }, "/v1/chat/completions")

    assert headers["x-api-key"] == "sk-test"
    assert body["model"] == "claude-upstream"
    assert body["system"] == "Use the tools."
    assert [block["type"] for block in body["messages"][1]["content"]] == [
        "text",
        "tool_use",
        "tool_use",
    ]
    assert body["messages"][2] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "call_a",
                "content": "18°C",
            },
            {
                "type": "tool_result",
                "tool_use_id": "call_b",
                "content": "24°C",
            },
        ],
    }
    assert body["tool_choice"] == {
        "type": "tool",
        "name": "weather",
        "disable_parallel_tool_use": True,
    }


async def test_openai_tool_choice_none_omits_anthropic_tools():
    channel = await Channel.create(
        name="anthropic-no-tools",
        provider="anthropic",
        base_url="https://api.anthropic.test",
        api_key="sk-test",
        models=["model"],
    )
    provider = AnthropicProvider(channel)
    _, _, body = provider.transform_request({
        "model": "model",
        "messages": [{"role": "user", "content": "No tools"}],
        "tools": [{
            "type": "function",
            "function": {"name": "weather", "parameters": {"type": "object"}},
        }],
        "tool_choice": "none",
    }, "/v1/chat/completions")
    assert "tools" not in body
    assert "tool_choice" not in body


async def test_non_stream_tool_responses_convert_both_directions():
    anthropic = openai_to_anthropic_response({
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Calling weather.",
                "tool_calls": [{
                    "id": "call_weather",
                    "type": "function",
                    "function": {
                        "name": "weather",
                        "arguments": '{"city":"深圳"}',
                    },
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 12,
            "prompt_cache_hit_tokens": 80,
        },
    }, "gateway-model")
    assert anthropic["stop_reason"] == "tool_use"
    assert anthropic["content"][1] == {
        "type": "tool_use",
        "id": "call_weather",
        "name": "weather",
        "input": {"city": "深圳"},
    }
    assert anthropic["usage"]["cache_read_input_tokens"] == 80

    channel = await Channel.create(
        name="anthropic-response-conversion",
        provider="anthropic",
        base_url="https://api.anthropic.test",
        api_key="sk-test",
        models=["gateway-model"],
    )
    openai = AnthropicProvider(channel).transform_response({
        "id": "msg_test",
        "model": "claude-upstream",
        "content": [
            {"type": "text", "text": "Calling weather."},
            {
                "type": "tool_use",
                "id": "toolu_weather",
                "name": "weather",
                "input": {"city": "深圳"},
            },
        ],
        "stop_reason": "tool_use",
        "usage": {
            "input_tokens": 20,
            "cache_read_input_tokens": 80,
            "cache_creation_input_tokens": 10,
            "output_tokens": 12,
        },
    }, "/v1/chat/completions")
    assert openai["choices"][0]["finish_reason"] == "tool_calls"
    call = openai["choices"][0]["message"]["tool_calls"][0]
    assert call["id"] == "toolu_weather"
    assert json.loads(call["function"]["arguments"]) == {"city": "深圳"}
    assert openai["usage"] == {
        "prompt_tokens": 110,
        "completion_tokens": 12,
        "total_tokens": 122,
        "prompt_tokens_details": {"cached_tokens": 80},
    }


async def test_openai_stream_to_anthropic_keeps_fragmented_parallel_tools_and_usage():
    chunks = [
        'data: {"choices":[{"delta":{"role":"assistant","content":"Checking "},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_a","type":"function","function":{"name":"weather","arguments":"{\\"city\\":\\"北"}}]},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"id":"call_b","type":"function","function":{"name":"weather","arguments":"{\\"city\\":\\"上"}}]},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"京\\"}"}},{"index":1,"function":{"arguments":"海\\"}"}}]},"finish_reason":"tool_calls"}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":100,"completion_tokens":15,"prompt_cache_hit_tokens":80}}',
        "data: [DONE]",
    ]

    converted = [
        item async for item in openai_stream_to_anthropic_stream(
            _lines(chunks), "gateway-model"
        )
    ]
    events = [data for line, _ in converted if (data := _sse_data(line))]
    tool_starts = [
        event for event in events
        if event.get("type") == "content_block_start"
        and event.get("content_block", {}).get("type") == "tool_use"
    ]
    arg_deltas = [
        event["delta"]["partial_json"] for event in events
        if event.get("type") == "content_block_delta"
        and event.get("delta", {}).get("type") == "input_json_delta"
    ]
    assert [event["content_block"]["id"] for event in tool_starts] == [
        "call_a",
        "call_b",
    ]
    assert [json.loads(value) for value in arg_deltas] == [
        {"city": "北京"},
        {"city": "上海"},
    ]
    message_delta = next(e for e in events if e.get("type") == "message_delta")
    assert message_delta["delta"]["stop_reason"] == "tool_use"
    assert message_delta["usage"]["cache_read_input_tokens"] == 80
    assert converted[-1][1] == {
        "prompt_tokens": 100,
        "completion_tokens": 15,
        "cached_tokens": 80,
    }


async def test_anthropic_stream_to_openai_keeps_fragmented_parallel_tools_and_usage():
    channel = await Channel.create(
        name="anthropic-stream-conversion",
        provider="anthropic",
        base_url="https://api.anthropic.test",
        api_key="sk-test",
        models=["gateway-model"],
    )
    provider = AnthropicProvider(channel)
    sse = "\n\n".join([
        'event: message_start\ndata: {"type":"message_start","message":{"model":"claude-upstream","usage":{"input_tokens":20,"cache_read_input_tokens":80,"cache_creation_input_tokens":10}}}',
        'event: content_block_start\ndata: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_a","name":"weather","input":{}}}',
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"city\\":\\"北京\\"}"}}',
        'event: content_block_start\ndata: {"type":"content_block_start","index":3,"content_block":{"type":"tool_use","id":"toolu_b","name":"weather","input":{}}}',
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":3,"delta":{"type":"input_json_delta","partial_json":"{\\"city\\":\\"上海\\"}"}}',
        'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":15}}',
        'event: message_stop\ndata: {"type":"message_stop"}',
    ]) + "\n\n"
    response = httpx.Response(200, content=sse)

    lines = [
        line async for line in provider.stream_transform(
            response, "/v1/chat/completions"
        )
    ]
    chunks = [data for line in lines if (data := _sse_data(line))]
    starts = [
        call for chunk in chunks
        for call in chunk.get("choices", [{}])[0].get("delta", {}).get("tool_calls", [])
        if call.get("id")
    ]
    assert [(call["index"], call["id"]) for call in starts] == [
        (0, "toolu_a"),
        (1, "toolu_b"),
    ]
    finish = next(
        chunk for chunk in chunks
        if chunk["choices"][0].get("finish_reason") is not None
    )
    assert finish["choices"][0]["finish_reason"] == "tool_calls"
    assert finish["usage"] == {
        "prompt_tokens": 110,
        "completion_tokens": 15,
        "total_tokens": 125,
        "prompt_tokens_details": {"cached_tokens": 80},
    }
    assert lines[-1] == "data: [DONE]\n\n"
