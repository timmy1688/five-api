"""Real services are opt-in and only use an explicitly named disposable database."""
import asyncio
import copy
import os
import re
import socket
from contextlib import AsyncExitStack, asynccontextmanager
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest
import redis.asyncio as redis
import uvicorn
from tortoise import Tortoise

from app.config import TORTOISE_ORM, settings
from app.main import create_app


class NamespacedRedis:
    def __init__(self, client, prefix):
        self.client, self.prefix = client, prefix

    def _key(self, key):
        return self.prefix + (key.decode() if isinstance(key, bytes) else str(key))

    async def eval(self, script, numkeys, *values):
        values = [self._key(value) if index < numkeys else value for index, value in enumerate(values)]
        return await self.client.eval(script, numkeys, *values)

    def __getattr__(self, name):
        async def call(*args, **kwargs):
            if name in {"mget", "exists", "delete"}:
                values = list(args[0]) if len(args) == 1 and isinstance(args[0], (list, tuple)) else list(args)
                transformed = [self._key(key) for key in values]
                if name == "mget":
                    return await self.client.mget(transformed, **kwargs)
                return await getattr(self.client, name)(*transformed, **kwargs)
            if args and name not in {"ping", "aclose"}:
                args = (self._key(args[0]), *args[1:])
            return await getattr(self.client, name)(*args, **kwargs)
        return call


@pytest.fixture(autouse=True)
async def setup_db(monkeypatch):
    local = os.environ.get("NO_PROXY", "") + ",127.0.0.1,localhost,::1"
    monkeypatch.setenv("NO_PROXY", local)
    monkeypatch.setenv("no_proxy", local)
    name = os.environ.get("FIVE_TEST_MYSQL_DB", "")
    if not name:
        pytest.skip("Set FIVE_TEST_MYSQL_DB and FIVE_TEST_REDIS_URL to run real-service tests")
    if not re.fullmatch(r"five_api_test_[A-Za-z0-9_]+", name) or name == settings.MYSQL_DATABASE:
        raise RuntimeError("Refusing to use a non-disposable MySQL database")
    config = copy.deepcopy(TORTOISE_ORM)
    config["connections"]["default"] = settings.database_url.rsplit("/", 1)[0] + "/" + name
    config["apps"]["models"]["models"] = ["app.models"]
    from app.services.settings_service import clear_settings_cache
    from app.services.alerts import clear_alert_cache
    from app.services.content_filter import clear_filter_cache
    from app.services.settlements import _unsaved
    clear_settings_cache(); clear_alert_cache(); clear_filter_cache(); _unsaved.clear()
    await Tortoise.init(config=config)
    await Tortoise.generate_schemas()
    yield
    from app.providers.base import close_http_clients
    await close_http_clients()
    from tortoise import connections
    connection = connections.get("default")
    tables = await connection.execute_query_dict("SHOW TABLES")
    names = [str(next(iter(row.values()))).replace("`", "``") for row in tables]
    await connection.execute_script("SET FOREIGN_KEY_CHECKS=0;" +
                                    "".join(f"DROP TABLE `{name}`;" for name in names) +
                                    "SET FOREIGN_KEY_CHECKS=1;")
    await Tortoise.close_connections()
    await Tortoise._reset_apps()


@pytest.fixture(autouse=True)
async def mock_redis():
    url = os.environ.get("FIVE_TEST_REDIS_URL", "")
    if not url:
        pytest.skip("FIVE_TEST_REDIS_URL is required")
    if urlsplit(url).path != "/15":
        raise RuntimeError("Integration Redis must explicitly use logical database 15")
    from uuid import uuid4
    raw = redis.from_url(url, decode_responses=True)
    prefix = "five:integration:" + uuid4().hex + ":"
    namespaced = NamespacedRedis(raw, prefix)
    async with AsyncExitStack() as stack:
        for module in ("app.dependencies", "app.services.concurrency", "app.services.rate_limit",
                       "app.services.sticky_session", "app.services.channel_health"):
            stack.enter_context(patch(module + ".get_redis", return_value=namespaced))
        yield namespaced
    keys = [key async for key in raw.scan_iter(match=prefix + "*")]
    if keys:
        await raw.delete(*keys)
    await raw.aclose()


@asynccontextmanager
async def serve(app, trusted="", ssl_keyfile=None, ssl_certfile=None):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.setblocking(False)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="critical", access_log=False,
        lifespan="off", proxy_headers=True, forwarded_allow_ips=trusted, timeout_graceful_shutdown=3,
        ssl_keyfile=ssl_keyfile, ssl_certfile=ssl_certfile,
    ))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    for _ in range(500):
        if server.started:
            break
        if task.done():
            await task
        await asyncio.sleep(0.01)
    if not server.started:
        raise RuntimeError("HTTP test server failed to start")
    try:
        yield f"{'https' if ssl_certfile else 'http'}://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=8)
        listener.close()


@pytest.fixture
async def gateway_url():
    async with serve(create_app()) as url:
        yield url
