from decimal import Decimal

import pytest

from app.models import Admin, APIKey, Channel, ModelPrice, RequestLog
from app.services.auth import hash_api_key, hash_password

pytestmark = pytest.mark.asyncio


async def test_admin_create():
    admin = await Admin.create(username="admin_m1", hashed_password=hash_password("pw"))
    assert admin.id is not None
    assert admin.is_active is True


async def test_channel_create():
    ch = await Channel.create(
        name="ch1",
        provider="openai",
        base_url="https://api.openai.com",
        api_key="sk-test",
        models=["gpt-4o"],
        model_mapping={"gpt-4": "gpt-4o"},
        model_pricing={"gpt-4o": {"prompt": 2.5, "completion": 10.0}},
    )
    assert ch.id is not None
    assert ch.models == ["gpt-4o"]
    assert ch.model_pricing["gpt-4o"]["prompt"] == 2.5


async def test_api_key_create():
    raw = "sk-model-test-key"
    k = await APIKey.create(
        name="test",
        key_hash=hash_api_key(raw),
        key_prefix=raw[:8],
        quota_total=Decimal("100"),
        quota_used=Decimal("0"),
    )
    assert k.id is not None
    assert k.quota_total == Decimal("100")
    assert k.quota_reset_day is None


async def test_api_key_with_reset_day():
    raw = "sk-reset-day-key"
    k = await APIKey.create(
        name="reset-key",
        key_hash=hash_api_key(raw),
        key_prefix=raw[:8],
        quota_total=Decimal("50"),
        quota_reset_day=15,
    )
    assert k.quota_reset_day == 15
    assert k.quota_last_reset_at is None


async def test_model_price_create():
    mp = await ModelPrice.create(
        model="gpt-4o-test",
        prompt_price=Decimal("2.5"),
        completion_price=Decimal("10.0"),
    )
    assert mp.id is not None
    assert mp.is_active is True
    assert mp.currency == "USD"


async def test_request_log_create():
    log = await RequestLog.create(
        request_id="req-001",
        api_key_id=1,
        api_key_name="test",
        channel_id=1,
        channel_name="ch1",
        model_requested="gpt-4o",
        model_actual="gpt-4o",
        provider="openai",
        endpoint="/v1/chat/completions",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost=Decimal("0.000750"),
        is_stream=False,
        status_code=200,
        latency_ms=320,
    )
    assert log.id is not None
    assert log.cost == Decimal("0.000750")
