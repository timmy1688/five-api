import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models import RequestLog
from tests.conftest import auth_header

pytestmark = pytest.mark.asyncio


async def _log(model, cost, when, channel_id=1):
    log = await RequestLog.create(
        request_id=uuid.uuid4().hex, api_key_id=1, model_requested=model,
        model_actual=model, channel_id=channel_id, cost=Decimal(cost), status_code=200,
    )
    await RequestLog.filter(id=log.id).update(created_at=when)


async def test_reconcile_matches_by_day_and_model(client, admin_token):
    await _log("claude-sonnet-4-5", "1.00", datetime(2026, 10, 1, 3, tzinfo=timezone.utc))
    await _log("claude-sonnet-4-5", "0.50", datetime(2026, 10, 1, 20, tzinfo=timezone.utc))
    await _log("claude-haiku-4-5", "0.20", datetime(2026, 10, 2, 1, tzinfo=timezone.utc))
    await _log("claude-haiku-4-5", "9.00", datetime(2026, 10, 2, 1, tzinfo=timezone.utc), channel_id=2)
    csv_text = (
        "Usage Date,Model,Cost (USD)\n"
        "2026-10-01,Claude Sonnet 4.5,$1.50\n"
        "2026-10-02,claude-haiku-4-5,0.40\n"
        "bad,row,x\n"
    )
    resp = await client.post(
        "/api/reconcile",
        files={"file": ("bill.csv", csv_text.encode(), "text/csv")},
        data={"channel_ids": "1"},
        headers=auth_header(admin_token),
    )
    body = resp.json()
    assert body["mapping"] == {"date": "Usage Date", "cost": "Cost (USD)", "model": "Model"}
    assert body["skipped"] == 1
    rows = {(r["date"], r["status"]) for r in body["rows"]}
    assert rows == {("2026-10-01", "match"), ("2026-10-02", "over")}
    assert body["totals"]["mismatches"] == 1
    assert body["totals"]["gateway_cost"] == pytest.approx(1.7)


async def test_reconcile_offset_shifts_days(client, admin_token):
    await _log("m", "1", datetime(2026, 10, 1, 20, tzinfo=timezone.utc))
    csv_text = "date,cost\n2026-10-02,1\n"
    resp = await client.post(
        "/api/reconcile",
        files={"file": ("bill.csv", csv_text.encode(), "text/csv")},
        data={"utc_offset": "8", "model_column": "-"},
        headers=auth_header(admin_token),
    )
    assert [r["status"] for r in resp.json()["rows"]] == ["match"]
