import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise

from app.main import create_app
from app.models import Admin, APIKey, Channel, ModelPrice, RequestLog
from app.services.auth import create_access_token, hash_api_key, hash_password

TEST_TORTOISE_ORM = {
    "connections": {"default": "sqlite://:memory:"},
    "apps": {
        "models": {
            "models": ["app.models"],
            "default_connection": "default",
        }
    },
}


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def setup_db():
    await Tortoise.init(config=TEST_TORTOISE_ORM)
    await Tortoise.generate_schemas()
    yield
    await Tortoise._drop_databases()
    await Tortoise.close_connections()


@pytest.fixture
async def admin():
    return await Admin.create(
        username="testadmin",
        hashed_password=hash_password("testpass123"),
    )


@pytest.fixture
def admin_token(admin):
    return create_access_token({"sub": admin.id})


@pytest.fixture
async def channel():
    return await Channel.create(
        name="test-openai",
        provider="openai",
        base_url="https://api.openai.com",
        api_key="sk-upstream-key",
        models=["gpt-4o", "gpt-4o-mini"],
        model_mapping={"gpt-4": "gpt-4o"},
        model_pricing={"gpt-4o": {"prompt": 2.5, "completion": 10.0}},
        priority=10,
        weight=1,
        is_enabled=True,
        timeout=60,
    )


@pytest.fixture
async def api_key():
    raw_key = "sk-testkey1234567890abcdef"
    return await APIKey.create(
        name="test-key",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        quota_total=Decimal("10.000000"),
        quota_used=Decimal("0"),
        concurrent_limit=5,
        allowed_models=[],
    ), raw_key


@pytest.fixture
async def model_price():
    return await ModelPrice.create(
        model="gpt-4o",
        prompt_price=Decimal("2.500000"),
        completion_price=Decimal("10.000000"),
    )


_mock_redis = AsyncMock()
_mock_redis.eval = AsyncMock(return_value=1)


@pytest.fixture(autouse=True)
def mock_redis():
    with patch("app.dependencies.get_redis", return_value=_mock_redis):
        with patch("app.services.concurrency.get_redis", return_value=_mock_redis):
            yield _mock_redis


@pytest.fixture
def app():
    application = create_app()
    return application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
