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
        self.hashes: dict[str, dict[str, int]] = {}

    async def ping(self):
        return True

    async def eval(self, script, numkeys, *keys_and_args):
        key = keys_and_args[0]
        args = keys_and_args[int(numkeys):]
        if "HVALS" in script:
            return self._quota_reserve(key, args)
        if "HDEL" in script:
            return self._quota_release(key, args)
        if "EXISTS" in script and "INCRBY" in script:
            return self._tpm_adjust(key, args)
        if "INCRBY" in script:
            return self._tpm_reserve(key, args)
        if "INCR" in script:
            return self._rpm(key, args)
        return 1

    def _quota_reserve(self, key, args):
        request_id, estimate, used, total, _ttl = args
        bucket = self.hashes.setdefault(key, {})
        if request_id in bucket:
            return 1
        held = sum(bucket.values())
        estimate, used, total = int(estimate), int(used), int(total)
        if used >= total or used + held + estimate > total:
            return 0
        bucket[request_id] = estimate
        return 1

    def _quota_release(self, key, args):
        bucket = self.hashes.get(key, {})
        bucket.pop(args[0], None)
        if not bucket:
            self.hashes.pop(key, None)
        return 1

    def _tpm_reserve(self, key, args):
        limit, amount, _window = (int(args[0]), int(args[1]), int(args[2]))
        current = int(self.data.get(key, 0))
        if current + amount > limit:
            return 0
        self.data[key] = str(current + amount)
        return 1

    def _tpm_adjust(self, key, args):
        delta = int(args[0])
        if key not in self.data or delta == 0:
            return 1
        nxt = int(self.data[key]) + delta
        if nxt <= 0:
            del self.data[key]
        else:
            self.data[key] = str(nxt)
        return 1

    def _rpm(self, key, args):
        limit = int(args[0])
        current = int(self.data.get(key, 0)) + 1
        if current > limit:
            return 0
        self.data[key] = str(current)
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

    async def decr(self, key):
        self.data[key] = str(int(self.data.get(key, 0)) - 1)
        return int(self.data[key])

    async def expire(self, *_):
        return True

    async def ttl(self, key):
        return 30 if key in self.data else -2


@pytest.fixture(autouse=True)
async def setup_db():
    from app.services.content_filter import clear_filter_cache
    from app.services.settings_service import clear_settings_cache

    clear_settings_cache()
    clear_filter_cache()
    await Tortoise.init(config=TEST_TORTOISE_ORM)
    await Tortoise.generate_schemas()
    yield
    from app.providers.base import close_http_clients
    from app.services.ai_audit import drain_ai_reviews

    await drain_ai_reviews()
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
        "app.services.quota.get_redis",
        "app.services.sticky_session.get_redis",
        "app.services.channel_health.get_redis",
    ]
    with patch(targets[0], return_value=fake), \
         patch(targets[1], return_value=fake), \
         patch(targets[2], return_value=fake), \
         patch(targets[3], return_value=fake), \
         patch(targets[4], return_value=fake), \
         patch(targets[5], return_value=fake):
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
