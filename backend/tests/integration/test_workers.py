"""Real Uvicorn workers sharing MySQL and Redis: accounting and crash takeover."""
import asyncio
import os
import signal
import socket
import sys
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import redis.asyncio as redis
from fastapi import FastAPI, Request

from app.models import APIKey, Channel, ModelPrice, RequestLog, Settlement, Tenant
from app.services.auth import hash_api_key
from app.services.cluster import PROCESS_KEY_PREFIX
from tests.integration.conftest import serve

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
ROOT = Path(__file__).resolve().parents[2]
MODEL = "worker-model"
STALE_SECONDS = 3


@asynccontextmanager
async def workers(tmp_path, count=2):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    env = {**os.environ, "MYSQL_DATABASE": os.environ["FIVE_TEST_MYSQL_DB"],
           "REDIS_URL": os.environ["FIVE_TEST_REDIS_URL"], "SECRETS_FILE": str(tmp_path / "secrets.json"),
           "WORKERS": str(count), "PROCESS_STALE_SECONDS": str(STALE_SECONDS)}
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
        "--workers", str(count), "--no-access-log", "--log-level", "warning", "--timeout-graceful-shutdown", "3",
        cwd=ROOT, env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=1) as client:
            for _ in range(150):
                try:
                    if (await client.get(base + "/healthz")).status_code == 200:
                        break
                except httpx.RequestError:
                    pass
                await asyncio.sleep(0.1)
            else:
                pytest.fail("Workers never became ready")
        yield base
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except TimeoutError:
                process.kill()
                await process.wait()


def upstream():
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        prompt = (await request.json())["messages"][0]["content"]
        await asyncio.sleep({"hang": 60, "slow": STALE_SECONDS * 2 + 2}.get(prompt, 0.2))
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10}}
    return app


async def ready(origin, quota, key_concurrency=-1):
    tenant = await Tenant.create(name="workers", quota_total=Decimal(quota), rpm_limit=-1, tpm_limit=-1,
                                 concurrent_limit=-1)
    raw = "sk-worker-integration-client"
    await APIKey.create(tenant_id=tenant.id, name="workers", key_hash=hash_api_key(raw), key_prefix=raw[:8],
                        quota_total=-1, concurrent_limit=key_concurrency)
    await Channel.create(name="workers", provider="openai", base_url=origin, models=[MODEL], api_key="",
                         max_retries=0, timeout=90, priority=10)
    # Output-only pricing makes the reservation for max_tokens equal to the final charge: 0.1 each.
    await ModelPrice.create(model=MODEL, prompt_price=0, completion_price=10000, cached_price=0, cache_write_price=0)
    return tenant, {"Authorization": "Bearer " + raw}


def body(prompt="hi"):
    return {"model": MODEL, "max_tokens": 10, "messages": [{"role": "user", "content": prompt}]}


async def test_two_workers_never_overspend_a_shared_tenant_budget(tmp_path):
    async with serve(upstream()) as origin, workers(tmp_path) as base:
        tenant, auth = await ready(origin, quota="3")
        async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
            responses = await asyncio.gather(*(client.post(base + "/v1/chat/completions", json=body(), headers=auth)
                                               for _ in range(60)))
        succeeded = sum(response.status_code == 200 for response in responses)
        assert succeeded == 30
        assert {response.status_code for response in responses} == {200, 429}
        tenant = await Tenant.get(id=tenant.id)
        assert tenant.quota_used == Decimal("3")
        logged = await RequestLog.filter(tenant_id=tenant.id, status_code=200).values_list("cost", flat=True)
        assert len(logged) == 30 and sum(logged) == Decimal("3")
        assert not await Settlement.filter(state__in=("reserved", "pending", "failed", "uncertain")).exists()
        assert len(set(await Settlement.filter(state="settled").values_list("owner_id", flat=True))) == 2


async def test_key_concurrency_limit_is_shared_by_all_workers(tmp_path):
    async with serve(upstream()) as origin, workers(tmp_path) as base:
        _, auth = await ready(origin, quota="10", key_concurrency=3)
        async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
            responses = await asyncio.gather(*(client.post(base + "/v1/chat/completions", json=body(), headers=auth)
                                               for _ in range(20)))
        assert 1 <= sum(response.status_code == 200 for response in responses) <= 3
        assert {response.status_code for response in responses} == {200, 429}


async def test_long_request_of_a_live_worker_is_not_taken_over(tmp_path):
    async with serve(upstream()) as origin, workers(tmp_path) as base:
        _, auth = await ready(origin, quota="10")
        async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
            request = asyncio.create_task(client.post(base + "/v1/chat/completions", json=body("slow"), headers=auth))
            seen = set()
            while not request.done():
                seen.update(await Settlement.all().values_list("state", flat=True))
                await asyncio.sleep(0.2)
            assert (await request).status_code == 200
        assert seen.isdisjoint({"released", "uncertain"})
        record = await Settlement.get()
        assert record.state == "settled" and record.last_error == ""


async def test_killed_worker_dispatched_reservation_becomes_uncertain_and_stays_held(tmp_path):
    raw = redis.from_url(os.environ["FIVE_TEST_REDIS_URL"], decode_responses=True)
    try:
        async with serve(upstream()) as origin, workers(tmp_path) as base:
            tenant, auth = await ready(origin, quota="10")
            async with httpx.AsyncClient(trust_env=False, timeout=60) as client:
                request = asyncio.create_task(client.post(base + "/v1/chat/completions", json=body("hang"),
                                                          headers=auth))
                async with asyncio.timeout(10):
                    while not await Settlement.filter(dispatched=True).exists():
                        await asyncio.sleep(0.05)
                record = await Settlement.get()
                pid = int(await raw.get(PROCESS_KEY_PREFIX + record.owner_id))
                os.kill(pid, signal.SIGKILL)
                with pytest.raises(httpx.HTTPError):
                    await request
            async with asyncio.timeout(STALE_SECONDS * 2 + 15):
                while (await Settlement.get(id=record.id)).state == "reserved":
                    await asyncio.sleep(0.2)
            record = await Settlement.get(id=record.id)
            assert record.state == "uncertain" and record.occupied == Decimal("0.1")
            assert (await Tenant.get(id=tenant.id)).quota_used == 0
    finally:
        await raw.aclose()
