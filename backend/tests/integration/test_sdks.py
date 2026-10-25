import json
import time

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from app.models import Channel, ModelPrice
from tests.integration.conftest import serve
from tests.integration.test_real_gateway import MODEL, ready

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_openai_sdk_chat_tools_stream_and_auth_errors(gateway_url):
    import openai
    app = FastAPI()
    seen = []
    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        seen.append(body)
        base = {"id": "chatcmpl_sdk", "created": int(time.time()), "model": MODEL}
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        if body.get("stream"):
            async def events():
                yield "data: " + json.dumps({**base, "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": "ok"}, "finish_reason": None}]}) + "\n\n"
                yield "data: " + json.dumps({**base, "object": "chat.completion.chunk", "choices": [], "usage": usage}) + "\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(events(), media_type="text/event-stream")
        return {**base, "object": "chat.completion", "usage": usage, "choices": [{
            "index": 0, "message": {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_1", "type": "function", "function": {"name": "add", "arguments": '{"a":1}'},
            }]}, "finish_reason": "tool_calls",
        }]}
    async with serve(app) as origin:
        _, raws = await ready(origin)
        async with openai.AsyncOpenAI(base_url=gateway_url + "/v1", api_key=raws[0], max_retries=0, timeout=5) as sdk:
            result = await sdk.chat.completions.create(model=MODEL, max_tokens=10,
                messages=[{"role": "user", "content": "call add"}],
                tools=[{"type": "function", "function": {"name": "add", "parameters": {"type": "object", "properties": {}}}}])
            assert result.choices[0].message.tool_calls[0].function.arguments == '{"a":1}'
            assert result._request_id
            stream = await sdk.chat.completions.create(model=MODEL, max_tokens=10, stream=True,
                                                        messages=[{"role": "user", "content": "hi"}])
            chunks = [chunk async for chunk in stream]
            assert chunks[0].choices[0].delta.content == "ok"
            assert seen[1]["stream_options"]["include_usage"] is True
        async with openai.AsyncOpenAI(base_url=gateway_url + "/v1", api_key="invalid-key", max_retries=0, timeout=5) as bad:
            with pytest.raises(openai.AuthenticationError) as error:
                await bad.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": "hi"}])
            assert error.value.status_code == 401


async def test_openai_sdk_responses_and_named_sse_events(gateway_url):
    import openai
    app = FastAPI()
    @app.post("/v1/responses")
    async def responses(request: Request):
        body = await request.json()
        result = {"id": "resp_sdk", "object": "response", "created_at": int(time.time()),
                  "status": "completed", "model": MODEL, "output": [{
                      "id": "msg_sdk", "type": "message", "status": "completed", "role": "assistant",
                      "content": [{"type": "output_text", "text": "ok", "annotations": []}],
                  }], "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}
        if body.get("stream"):
            async def events():
                for kind, data in [
                    ("response.created", {"response": {**result, "status": "in_progress", "output": []}}),
                    ("response.output_text.delta", {"delta": "ok", "item_id": "msg_sdk", "output_index": 0, "content_index": 0}),
                    ("response.completed", {"response": result}),
                ]:
                    yield f"event: {kind}\ndata: " + json.dumps({"type": kind, **data}) + "\n\n"
            return StreamingResponse(events(), media_type="text/event-stream")
        return result
    async with serve(app) as origin:
        _, raws = await ready(origin)
        async with openai.AsyncOpenAI(base_url=gateway_url + "/v1", api_key=raws[0], max_retries=0, timeout=5) as sdk:
            result = await sdk.responses.create(model=MODEL, input="hi", max_output_tokens=10)
            assert result.output_text == "ok"
            stream = await sdk.responses.create(model=MODEL, input="hi", max_output_tokens=10, stream=True)
            events = [event async for event in stream]
            assert [event.type for event in events] == ["response.created", "response.output_text.delta", "response.completed"]


async def test_anthropic_sdk_messages_tools_and_stream(gateway_url):
    import anthropic
    app = FastAPI()
    seen = []
    @app.post("/v1/messages")
    async def messages(request: Request):
        body = await request.json()
        seen.append(body)
        base = {"id": "msg_sdk", "type": "message", "role": "assistant", "model": MODEL,
                "content": [], "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 0}}
        if body.get("stream"):
            async def events():
                for kind, data in [
                    ("message_start", {"message": base}),
                    ("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
                    ("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "ok"}}),
                    ("content_block_stop", {"index": 0}),
                    ("message_delta", {"delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 5}}),
                    ("message_stop", {}),
                ]:
                    yield f"event: {kind}\ndata: " + json.dumps({"type": kind, **data}) + "\n\n"
            return StreamingResponse(events(), media_type="text/event-stream")
        return {**base, "stop_reason": "tool_use", "content": [{
                    "type": "tool_use", "id": "toolu_sdk", "name": "add", "input": {"a": 1},
                }], "usage": {"input_tokens": 10, "output_tokens": 5}}
    async with serve(app) as origin:
        _, raws = await ready(origin)
        await Channel.all().update(provider="anthropic")
        async with anthropic.AsyncAnthropic(base_url=gateway_url, api_key=raws[0], max_retries=0, timeout=5) as sdk:
            result = await sdk.messages.create(model=MODEL, max_tokens=10, messages=[{"role": "user", "content": "add"}],
                tools=[{"name": "add", "description": "Add", "input_schema": {"type": "object", "properties": {}}}])
            assert result.content[0].type == "tool_use"
            async with sdk.messages.stream(model=MODEL, max_tokens=10, messages=[{"role": "user", "content": "hi"}]) as stream:
                text = "".join([piece async for piece in stream.text_stream])
                final = await stream.get_final_message()
            assert text == "ok" and final.usage.input_tokens == 10
            assert seen[0]["tools"][0]["name"] == "add"
