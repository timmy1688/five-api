from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from httpx import Request, Response

from app.models import APIKey, Channel, ModelProbe, Tenant
from app.services.model_monitor import run_due_once
from app.services.settings_service import gateway_config, patch_gateway_config
from tests.conftest import auth_header, create_tenant_account
from tests.test_billing_reliability import upstream
from tests.test_model_hub import synthetic_response

pytestmark = pytest.mark.asyncio


async def test_platform_key_creation_is_separate_from_customer_tenants(client, admin_token):
    customer, _, _ = await create_tenant_account()
    headers = auth_header(admin_token)
    created = await client.post("/api/keys", json={"name": "internal"}, headers=headers)
    assert created.status_code == 201 and created.json()["tenant_is_system"]
    platform = await Tenant.get(id=created.json()["tenant_id"])
    assert platform.is_system and platform.quota_total == -1
    assert created.json()["tenant_id"] != customer.id
    listed = await client.get("/api/tenants", headers=headers)
    assert all(row["id"] != platform.id for row in listed.json()["items"])
    assert (await client.post("/api/keys", json={"name": "impersonate", "tenant_id": customer.id}, headers=headers)).status_code == 422


async def test_schedules_default_to_fifteen_minutes_and_one_day(client, admin_token):
    response = await client.get("/api/models/check-settings", headers=auth_header(admin_token))
    assert response.json()["config"] == {"health_enabled": True, "health_interval_seconds": 900,
                                        "capability_enabled": True, "capability_interval_seconds": 86400}


async def test_scheduler_runs_due_models_and_uses_sql_history_after_restart():
    await Channel.create(name="scheduled", provider="openai", models=["gpt-4o"], api_key="", base_url="https://scheduled.test")
    def respond(url, **kwargs):
        return Response(200, json=synthetic_response(kwargs["json"]), request=Request("POST", url))
    with patch("app.providers.base._shared_http_client", return_value=upstream(respond)):
        assert await run_due_once() == 2
        assert await run_due_once() == 0
        # No process-local schedule cache is required to avoid duplicate probes.
        assert await run_due_once(now=datetime.now(timezone.utc)+timedelta(minutes=16)) == 1
    records = await ModelProbe.all()
    assert len(records) == 3 and all(row.run_source == "scheduled" and row.actor_id == 0 for row in records)


async def test_scheduler_skips_disabled_channels_unsupported_models_and_capability_families():
    await Channel.create(name="off", provider="openai", models=["gpt-4o"], api_key="", base_url="https://off.test", is_enabled=False)
    await Channel.create(name="other", provider="openai", models=["deepseek-v4-flash", "text-embedding-3-small"], api_key="", base_url="https://other.test")
    http = upstream(lambda url, **kwargs: Response(200, json=synthetic_response(kwargs["json"]), request=Request("POST", url)))
    with patch("app.providers.base._shared_http_client", return_value=http):
        assert await run_due_once() == 1
    row = await ModelProbe.get()
    assert row.model == "deepseek-v4-flash" and row.kind == "health"


async def test_scheduler_can_be_disabled_without_changing_other_settings(client, admin_token):
    before = await gateway_config()
    headers = auth_header(admin_token)
    response = await client.put("/api/models/check-settings", json={
        "health_enabled": False, "health_interval_seconds": 1200,
        "capability_enabled": False, "capability_interval_seconds": 43200,
    }, headers=headers)
    assert response.status_code == 200
    after = await gateway_config()
    assert after["log_retention_days"] == before["log_retention_days"]
    assert after["routing_strategy"] == before["routing_strategy"]
    assert await run_due_once() == 0


async def test_tenant_cannot_read_or_change_schedule(client):
    _, _, headers = await create_tenant_account()
    assert (await client.get("/api/models/check-settings", headers=headers)).status_code == 403
    assert (await client.put("/api/models/check-settings", json={}, headers=headers)).status_code == 403
