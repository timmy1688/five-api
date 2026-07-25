from decimal import Decimal
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise

from app.main import create_app
from app.models import APIKey, Channel, ModelPrice, Role, User
from app.services.auth import ALL_PERMISSIONS, create_access_token, hash_api_key, hash_password

TEST_TORTOISE_ORM = {
    "connections": {"default": "sqlite://:memory:"},
    "apps": {"models": {"models": ["app.models"], "default_connection": "default"}},
}


async def create_admin(username: str, password: str = "pw") -> User:
    role, _ = await Role.get_or_create(
        name="Super Admin",
        defaults={"permissions": ALL_PERMISSIONS, "is_builtin": True},
    )
    return await User.create(
        username=username, hashed_password=hash_password(password), role=role
    )


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def eval(self, *_):
        return 1

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = str(value)

    async def delete(self, *keys):
        return sum(self.data.pop(key, None) is not None for key in keys)

    async def exists(self, *keys):
        return sum(key in self.data for key in keys)

    async def incr(self, key):
        self.data[key] = str(int(self.data.get(key, 0)) + 1)
        return int(self.data[key])

    async def expire(self, *_):
        return True

    async def ttl(self, key):
        return 30 if key in self.data else -2


@pytest.fixture(autouse=True)
async def setup_db():
    await Tortoise.init(config=TEST_TORTOISE_ORM)
    await Tortoise.generate_schemas()
    yield
    from app.providers.base import close_http_clients
    await close_http_clients()
    await Tortoise._drop_databases()


@pytest.fixture
async def admin():
    return await create_admin("testadmin", "testpass123")


@pytest.fixture
def admin_token(admin):
    return create_access_token({"sub": str(admin.id)})


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
        timeout=60,
    )


@pytest.fixture
async def api_key():
    raw_key = "sk-testkey1234567890abcdef"
    return await APIKey.create(
        name="test-key",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        quota_total=Decimal("10"),
        concurrent_limit=5,
    ), raw_key


@pytest.fixture
async def model_price():
    return await ModelPrice.create(
        model="gpt-4o",
        prompt_price=Decimal("2.5"),
        completion_price=Decimal("10"),
    )


@pytest.fixture(autouse=True)
def mock_redis():
    fake = FakeRedis()
    targets = [
        "app.dependencies.get_redis",
        "app.services.concurrency.get_redis",
        "app.services.rate_limit.get_redis",
        "app.services.sticky_session.get_redis",
        "app.services.channel_health.get_redis",
    ]
    with patch(targets[0], return_value=fake), \
         patch(targets[1], return_value=fake), \
         patch(targets[2], return_value=fake), \
         patch(targets[3], return_value=fake), \
         patch(targets[4], return_value=fake):
        yield fake


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
