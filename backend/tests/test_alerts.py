from tests.conftest import create_test_tenant
import base64
import hashlib
import hmac
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app import dependencies
from app.models import APIKey, Channel
from app.services import alerts, channel_health
from app.services.auth import hash_api_key
from tests.conftest import auth_header

pytestmark = pytest.mark.asyncio

HOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/abcdef123456"


async def _enable(**overrides):
    config = {
        "enabled": True,
        "webhooks": [{"type": "feishu", "name": "ops", "url": HOOK_URL, "secret": "s3cret"}],
        **overrides,
    }
    return await alerts.save_config(config)


async def test_settings_mask_url_and_keep_secret(client, admin_token):
    headers = auth_header(admin_token)
    body = {"enabled": True, "webhooks": [{"type": "feishu", "name": "ops", "url": HOOK_URL, "secret": "s3cret"}]}
    saved = (await client.put("/api/settings/alerts", json=body, headers=headers)).json()
    hook = saved["webhooks"][0]
    assert HOOK_URL not in str(saved) and "s3cret" not in str(saved)
    assert hook["url"].startswith("https://open.feishu.cn/••••") and hook["has_secret"]

    again = {"enabled": True, "webhooks": [{"id": hook["id"], "type": "feishu", "name": "ops2", "url": hook["url"]}]}
    resaved = (await client.put("/api/settings/alerts", json=again, headers=headers)).json()
    assert resaved["webhooks"][0]["name"] == "ops2" and resaved["webhooks"][0]["has_secret"]
    stored = (await alerts.alert_config())["webhooks"][0]
    url, _ = alerts.build_request(stored, "test", "t", "x", {})
    assert url == HOOK_URL


async def test_test_endpoint_reports_results(client, admin_token):
    await _enable()
    with patch.object(alerts, "deliver", AsyncMock(return_value=[{"ok": True}])) as deliver:
        resp = await client.post("/api/settings/alerts/test", json={}, headers=auth_header(admin_token))
    assert resp.json() == {"items": [{"ok": True}]}
    assert deliver.await_count == 1


def test_signatures():
    feishu = {"type": "feishu", "url": alerts.encrypt_secret(HOOK_URL), "secret": alerts.encrypt_secret("k")}
    _, payload = alerts.build_request(feishu, "e", "title", "text", {})
    expected = hmac.new(f"{payload['timestamp']}\nk".encode(), b"", hashlib.sha256).digest()
    assert payload["sign"] == base64.b64encode(expected).decode()
    assert payload["content"]["text"] == "title\ntext"

    ding = {"type": "dingtalk", "url": alerts.encrypt_secret("https://oapi.dingtalk.com/robot/send?access_token=x"), "secret": alerts.encrypt_secret("k")}
    url, payload = alerts.build_request(ding, "e", "title", "text", {})
    assert "&timestamp=" in url and "&sign=" in url
    assert payload == {"msgtype": "text", "text": {"content": "title\ntext"}}


async def test_channel_open_and_recover_alert_once():
    await _enable()
    channel = await Channel.create(name="claude-main", provider="anthropic", base_url="https://x", api_key="", models=["m"])
    with patch.object(alerts, "deliver", AsyncMock(return_value=[])) as deliver:
        for _ in range(5):
            await channel_health.record_failure(channel.id)
        await alerts.drain_alerts()
        assert deliver.await_count == 1
        assert "claude-main" in deliver.await_args.args[2]
        await channel_health.record_success(channel.id)
        await channel_health.record_success(channel.id)
        await alerts.drain_alerts()
    assert deliver.await_count == 2
    assert "渠道恢复" in deliver.await_args.args[2]


async def test_error_spike_alerts_once():
    await _enable(error_min_requests=4, error_threshold=0.5)
    with patch.object(alerts, "deliver", AsyncMock(return_value=[])) as deliver:
        for status in (200, 502, 502, 500, 502, 502):
            await alerts.record_outcome(status)
        await alerts.drain_alerts()
    assert deliver.await_count == 1
    assert deliver.await_args.args[4] == {"requests": 4, "errors": 3, "rate": 0.75}


async def test_budget_alert_respects_threshold_and_switch():
    key = await APIKey.create(tenant_id=(await create_test_tenant()).id,
        name="dev", key_hash=hash_api_key("sk-alert"), key_prefix="sk-alert",
        quota_total=Decimal("10"), quota_used=Decimal("8"),
    )
    await _enable(budget_threshold=0.9)
    with patch.object(alerts, "deliver", AsyncMock(return_value=[])) as deliver:
        await alerts.check_budget(key.id)
        await APIKey.filter(id=key.id).update(quota_used=Decimal("9.5"))
        await alerts.check_budget(key.id)
        await alerts.check_budget(key.id)
        await alerts.drain_alerts()
        assert deliver.await_count == 1
        await _enable(events={"budget": False})
        await (await dependencies.get_redis()).delete(f"five:alert:budget:key:{key.id}:quota")
        await alerts.check_budget(key.id)
        await alerts.drain_alerts()
    assert deliver.await_count == 1


async def test_disabled_alerts_do_nothing():
    with patch.object(alerts, "deliver", AsyncMock(return_value=[])) as deliver:
        await alerts.record_outcome(500)
        assert await alerts.notify("errors", "x", "t", "x", {}, 60) is False
    deliver.assert_not_awaited()
