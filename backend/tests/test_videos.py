from tests.conftest import create_test_tenant
from app.services.video_jobs import find_video, forget_video, remember_video
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.models import APIKey, Channel, ModelPrice, RequestLog
from app.services.auth import hash_api_key
from tests.conftest import auth_header

pytestmark = pytest.mark.asyncio


async def test_identical_video_ids_do_not_overwrite_other_key_jobs():
    for owner, channel in ((101, 10), (202, 20)):
        await remember_video("same-id", channel_id=channel, api_key_id=owner,
                             upstream_key="test-upstream", model="test-model", seconds=4)
    assert (await find_video("same-id", 101))["channel_id"] == 10
    assert (await find_video("same-id", 202))["channel_id"] == 20
    await forget_video("same-id", 101)
    assert await find_video("same-id", 101) is None
    assert (await find_video("same-id", 202))["channel_id"] == 20

RAW_KEY = "sk-video-owner-key"
OTHER_KEY = "sk-video-other-key"


async def _env():
    ch = await Channel.create(
        name="video-ch", provider="openai", base_url="https://api.openai.test",
        api_key="sk-up-a\nsk-up-b", models=["sora-2"], model_mapping={"sora-2": "sora-2-2026"}, timeout=60,
    )
    await APIKey.create(tenant_id=(await create_test_tenant()).id, name="owner", key_hash=hash_api_key(RAW_KEY), key_prefix=RAW_KEY[:8], quota_total=Decimal("100"))
    await APIKey.create(tenant_id=(await create_test_tenant()).id, name="other", key_hash=hash_api_key(OTHER_KEY), key_prefix=OTHER_KEY[:8], quota_total=Decimal("100"))
    await ModelPrice.create(model="sora-2-2026", request_price=Decimal("0.10"))
    return ch


def _http(*responses: httpx.Response):
    http = AsyncMock()
    http.is_closed = False
    http.request = AsyncMock(side_effect=list(responses))
    return http


def _resp(status=200, json=None, content=None, content_type=None):
    kwargs = {"json": json} if json is not None else {"content": content, "headers": {"content-type": content_type}}
    return httpx.Response(status, request=httpx.Request("GET", "https://api.openai.test/v1/videos"), **kwargs)


def _bearer(call) -> str:
    return call.kwargs["headers"]["Authorization"]


async def test_video_is_billed_per_second_and_polled_on_its_channel(client):
    await _env()
    job = {"id": "video_1", "object": "video", "status": "queued", "seconds": "8"}
    http = _http(
        _resp(json=job),
        _resp(json={**job, "status": "completed"}),
        _resp(content=b"MP4DATA", content_type="video/mp4"),
        _resp(json={"id": "video_1", "deleted": True}),
    )
    with patch("app.providers.base._shared_http_client", return_value=http):
        created = await client.post(
            "/v1/videos", json={"model": "sora-2", "prompt": "a cat", "seconds": "8"},
            headers=auth_header(RAW_KEY),
        )
        assert created.status_code == 200
        create_call = http.request.await_args_list[0]
        assert create_call.args[:2] == ("POST", "v1/videos")
        assert create_call.kwargs["json"]["model"] == "sora-2-2026"

        assert (await client.get("/v1/videos/video_1", headers=auth_header(OTHER_KEY))).status_code == 404

        status = await client.get("/v1/videos/video_1", headers=auth_header(RAW_KEY))
        assert status.json()["status"] == "completed"
        content = await client.get("/v1/videos/video_1/content?variant=video", headers=auth_header(RAW_KEY))
        assert content.content == b"MP4DATA"
        assert content.headers["content-type"] == "video/mp4"
        deleted = await client.delete("/v1/videos/video_1", headers=auth_header(RAW_KEY))
        assert deleted.status_code == 200
        assert (await client.get("/v1/videos/video_1", headers=auth_header(RAW_KEY))).status_code == 404

    calls = http.request.await_args_list
    assert calls[1].args[:2] == ("GET", "v1/videos/video_1")
    assert calls[2].kwargs["params"] == {"variant": "video"}
    assert calls[3].args[:2] == ("DELETE", "v1/videos/video_1")
    assert {_bearer(call) for call in calls} == {_bearer(create_call)}

    log = await RequestLog.get()
    assert (log.endpoint, log.cost) == ("/v1/videos", Decimal("0.8"))
    assert (await APIKey.get(name="owner")).quota_used == Decimal("0.8")


async def test_multipart_video_forwards_the_reference_image(client):
    await _env()
    http = _http(_resp(json={"id": "video_2", "status": "queued"}))
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/videos",
            data={"model": "sora-2", "prompt": "move"},
            files={"input_reference": ("ref.png", b"PNG", "image/png")},
            headers=auth_header(RAW_KEY),
        )
    assert resp.status_code == 200
    kwargs = http.request.await_args.kwargs
    assert kwargs["data"] == {"model": "sora-2-2026", "prompt": "move"}
    assert kwargs["files"][0][0] == "input_reference"
    assert (await RequestLog.get()).cost == Decimal("0.4")


async def test_remix_stays_on_the_source_channel_and_key(client):
    await _env()
    http = _http(_resp(json={"id": "video_3"}), _resp(json={"id": "video_4"}))
    with patch("app.providers.base._shared_http_client", return_value=http):
        source = await client.post(
            "/v1/videos", json={"model": "sora-2", "prompt": "a", "seconds": "12"},
            headers=auth_header(RAW_KEY),
        )
        assert source.status_code == 200
        await Channel.create(
            name="video-backup", provider="openai", base_url="https://backup.test",
            api_key="sk-backup", models=["sora-2"], priority=10, timeout=60,
        )
        remix = await client.post(
            "/v1/videos/video_3/remix", json={"prompt": "b"}, headers=auth_header(RAW_KEY),
        )
    assert remix.status_code == 200
    first, second = http.request.await_args_list
    assert second.args[:2] == ("POST", "v1/videos/video_3/remix")
    assert second.kwargs["json"] == {"prompt": "b"}
    assert _bearer(second) == _bearer(first)
    logs = await RequestLog.all().order_by("id")
    assert [log.channel_name for log in logs] == ["video-ch", "video-ch"]
    assert logs[1].cost == Decimal("1.2")
