import httpx
import pytest
from fastapi import FastAPI, Request

from app.models import Channel, ModelProbe, User
from app.services.auth import create_access_token, hash_password
from app.services.model_monitor import run_due_once
from tests.integration.conftest import serve
from tests.test_model_hub import synthetic_response

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_real_http_manual_and_scheduled_checks_share_redis_and_sql_history(gateway_url, mock_redis):
    origin = FastAPI()
    @origin.post("/v1/chat/completions")
    async def chat(request: Request):
        return synthetic_response(await request.json())
    admin = await User.create(username="monitor-operator", role="platform_admin", hashed_password=hash_password("password"))
    headers = {"Authorization": "Bearer " + create_access_token({"sub": str(admin.id)})}
    async with serve(origin) as url:
        channel = await Channel.create(name="real-model-check", provider="openai", base_url=url, api_key="", models=["gpt-4o"])
        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            response = await client.post(gateway_url + "/api/models/probe",
                json={"channel_id": channel.id, "model": "gpt-4o", "kind": "health"}, headers=headers)
            assert response.status_code == 200 and response.json()["status"] == "healthy"
            assert await run_due_once() == 1  # only capability remains due
            assert await run_due_once() == 0
            catalog = (await client.get(gateway_url + "/api/models", headers=headers)).json()["items"][0]
            assert catalog["health"] == "healthy" and catalog["channels"][0]["capability"]["score"] == 100
            assert catalog["channels"][0]["next_health_at"]
        assert await ModelProbe.filter(run_source="scheduled").count() == 1
        assert await mock_redis.zcard("five:concurrency:model_probe_global:0") == 0
