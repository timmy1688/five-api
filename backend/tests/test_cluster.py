"""Coordination between workers sharing MySQL and Redis."""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.main import init_admin
from app.models import Channel, Settlement, User
from app.services import channel_health as health
from app.services import cluster, model_monitor, settlements
from tests.conftest import create_test_tenant

LIVE, EXITED = "live-worker", "exited-worker"


@pytest.fixture
def alerts():
    with patch.object(health.alerts, "channel_opened", AsyncMock()), \
            patch.object(health.alerts, "channel_recovered", AsyncMock()):
        yield


async def held(request_id, owner, dispatched, age_seconds):
    tenant = await create_test_tenant()
    record = await Settlement.create(request_id=request_id, tenant_id=tenant.id, api_key_id=1,
                                     occupied=Decimal("1.5"), owner_id=owner, dispatched=dispatched)
    created = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    await Settlement.filter(id=record.id).update(created_at=created)
    return record


async def state(request_id):
    record = await Settlement.get(request_id=request_id)
    return record.state, record.occupied


async def test_takeover_only_touches_old_reservations_of_exited_workers(mock_redis):
    await mock_redis.set(cluster.PROCESS_KEY_PREFIX + LIVE, "1")
    old = settings.PROCESS_STALE_SECONDS + 5
    await held("live-old", LIVE, True, old)
    await held("exited-undispatched", EXITED, False, old)
    await held("exited-dispatched", EXITED, True, old)
    await held("exited-recent", EXITED, True, 1)
    await held("self-old", cluster.OWNER_ID, False, old)

    assert await settlements.recover_orphans() == 2

    assert await state("live-old") == ("reserved", Decimal("1.5"))
    assert await state("exited-undispatched") == ("released", Decimal("0"))
    # The upstream may have charged for it, so the estimate stays held for reconciliation.
    assert await state("exited-dispatched") == ("uncertain", Decimal("1.5"))
    assert await state("exited-recent") == ("reserved", Decimal("1.5"))
    assert await state("self-old") == ("reserved", Decimal("1.5"))


async def test_takeover_keeps_everything_when_heartbeats_are_unreadable():
    await held("exited-dispatched", EXITED, True, settings.PROCESS_STALE_SECONDS + 5)
    with patch.object(cluster, "live_owners", side_effect=ConnectionError("redis down")):
        assert await settlements.recover_orphans() == 0
    assert await state("exited-dispatched") == ("reserved", Decimal("1.5"))


async def test_usage_reported_after_takeover_settles_actual_cost():
    record = await held("late", EXITED, True, settings.PROCESS_STALE_SECONDS + 5)
    await settlements.recover_orphans()
    assert (await state("late"))[0] == "uncertain"
    await settlements.mark_pending("late", {"model": "m"}, Decimal("0.4"))
    refreshed = await Settlement.get(id=record.id)
    assert refreshed.state == "pending" and refreshed.occupied == Decimal("0.4")


async def test_undispatched_takeover_blocks_the_upstream_call():
    await held("slow-start", EXITED, False, settings.PROCESS_STALE_SECONDS + 5)
    await settlements.recover_orphans()
    with pytest.raises(RuntimeError, match="before upstream dispatch"):
        await settlements.mark_dispatched("slow-start")


async def test_heartbeat_marks_this_worker_live_until_it_leaves():
    await cluster.beat()
    assert await cluster.live_owners([cluster.OWNER_ID, EXITED]) == {cluster.OWNER_ID}
    await cluster.leave()
    assert await cluster.live_owners([cluster.OWNER_ID]) == set()


async def test_claim_admits_one_worker_per_period():
    results = await asyncio.gather(*(cluster.claim("job", 60) for _ in range(5)))
    assert results.count(True) == 1


async def test_each_open_channel_is_probed_by_one_worker_per_period(alerts):
    channels = [await Channel.create(name=f"c{index}", provider="openai", base_url="https://u.example.com",
                                     api_key="k") for index in range(3)]
    for channel in channels:
        for _ in range(3):
            await health.record_failure(channel.id)
    probed = []

    async def probe(channel):
        probed.append(channel.id)
        return False

    async def worker():
        sleeps = 0

        async def sleep(_seconds):
            nonlocal sleeps
            sleeps += 1
            if sleeps > 1:
                raise asyncio.CancelledError

        with patch.object(health.asyncio, "sleep", sleep):
            with pytest.raises(asyncio.CancelledError):
                await health.health_check_loop()

    with patch.object(health, "_probe_channel", probe):
        await worker()
        await worker()
    assert sorted(probed) == sorted(channel.id for channel in channels)


async def test_concurrent_startup_tolerates_the_admin_created_by_another_worker():
    await User.create(username=settings.INIT_ADMIN_USERNAME, hashed_password="x", role="platform_admin")
    with patch.object(User, "exists", AsyncMock(side_effect=[False, True])):
        await init_admin()
    assert await User.filter(role="platform_admin").count() == 1


async def test_scheduler_status_is_shared_through_redis(mock_redis):
    assert (await model_monitor.scheduler_status())["running"] is False
    await mock_redis.set(model_monitor.RUNTIME_KEY,
                         '{"last_sweep_at": "2026-10-31T00:00:00+00:00", "next_sweep_at": "2026-10-31T00:00:30+00:00"}')
    status = await model_monitor.scheduler_status()
    assert status == {"running": True, "last_sweep_at": "2026-10-31T00:00:00+00:00",
                      "next_sweep_at": "2026-10-31T00:00:30+00:00"}


def test_pool_size_keeps_total_connections_bounded(monkeypatch):
    monkeypatch.setattr(settings, "MYSQL_POOL_SIZE", 0)
    for workers, size in ((1, 50), (4, 50), (8, 25), (64, 10)):
        monkeypatch.setattr(settings, "WORKERS", workers)
        assert settings.mysql_pool_size == size
    monkeypatch.setattr(settings, "MYSQL_POOL_SIZE", 7)
    assert settings.mysql_pool_size == 7
