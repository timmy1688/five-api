"""Compare a vendor bill CSV with what the gateway billed for the same days.

Vendor exports differ, so the caller maps three columns: date, cost and an
optional model. Gateway totals come from request logs grouped by the actual
upstream model, which is the name vendors bill by. Log retention bounds how
far back a bill can be checked.
"""

import csv
import io
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from tortoise import connections

from app.models import User
from app.services.auth import require_permission

router = APIRouter(prefix="/api/reconcile", tags=["reconcile"])

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 200_000
# A gap counts as a mismatch when it passes both limits.
ABS_TOLERANCE = Decimal("0.01")
REL_TOLERANCE = Decimal("0.05")

_GUESSES = {
    "date": ("date", "day", "usage_date", "time", "timestamp", "start_time", "日期", "时间"),
    "model": ("model", "model_name", "model_id", "sku", "product", "模型"),
    "cost": ("cost", "cost_usd", "amount", "amount_usd", "usd", "total_cost", "price", "费用", "金额"),
}
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y")


def _normalize_model(name: str) -> str:
    return re.sub(r"[\s_.]+", "-", name.strip().lower())


def _guess(columns: list[str], field: str) -> str:
    lowered = {c.strip().lower(): c for c in columns}
    for candidate in _GUESSES[field]:
        if candidate in lowered:
            return lowered[candidate]
    for column in columns:
        if any(candidate in column.lower() for candidate in _GUESSES[field]):
            return column
    return ""


def _parse_date(raw: str) -> date | None:
    value = (raw or "").strip()
    if not value:
        return None
    if value.isdigit() and len(value) >= 10:
        stamp = int(value[:10])
        return datetime.fromtimestamp(stamp, tz=timezone.utc).date()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    head = value.split("T")[0].split(" ")[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return None


def _parse_cost(raw: str) -> Decimal | None:
    cleaned = re.sub(r"[^0-9.\-eE]", "", (raw or "").replace(",", ""))
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _read_csv(data: bytes) -> tuple[list[str], list[dict]]:
    text = data.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    columns = [c for c in (reader.fieldnames or []) if c is not None]
    rows = []
    for index, row in enumerate(reader):
        if index >= MAX_ROWS:
            break
        rows.append(row)
    return columns, rows


async def _gateway_totals(
    start: date, end: date, channel_ids: list[int], utc_offset: int, by_model: bool,
) -> dict[tuple[str, str], dict]:
    conn = connections.get("default")
    sqlite = conn.capabilities.dialect == "sqlite"
    mark = "?" if sqlite else "%s"
    if sqlite:
        day_expr = f"date(datetime(created_at, '{utc_offset:+d} hours'))"
    else:
        day_expr = f"DATE(DATE_ADD(created_at, INTERVAL {utc_offset} HOUR))"
    model_expr = "model_actual" if by_model else "''"
    since = datetime.combine(start, datetime.min.time()) - timedelta(hours=utc_offset)
    until = datetime.combine(end + timedelta(days=1), datetime.min.time()) - timedelta(hours=utc_offset)
    where = [f"created_at >= {mark}", f"created_at < {mark}", "status_code < 400"]
    params: list = [since.isoformat(sep=" "), until.isoformat(sep=" ")]
    if channel_ids:
        where.append(f"channel_id IN ({', '.join(mark for _ in channel_ids)})")
        params.extend(channel_ids)
    sql = (
        f"SELECT {day_expr} AS d, {model_expr} AS m, COUNT(*) AS n, SUM(cost) AS c, "
        "SUM(prompt_tokens) AS p, SUM(completion_tokens) AS o "
        f"FROM request_logs WHERE {' AND '.join(where)} GROUP BY d, m"
    )
    rows = await conn.execute_query_dict(sql, params)
    totals: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (str(r["d"])[:10], _normalize_model(r["m"] or "") if by_model else "")
        bucket = totals.setdefault(key, {"cost": Decimal(0), "requests": 0, "tokens": 0, "names": set()})
        bucket["cost"] += Decimal(str(r["c"] or 0))
        bucket["requests"] += int(r["n"] or 0)
        bucket["tokens"] += int(r["p"] or 0) + int(r["o"] or 0)
        if by_model and r["m"]:
            bucket["names"].add(r["m"])
    return totals


def _status(vendor: Decimal, gateway: Decimal) -> str:
    gap = abs(vendor - gateway)
    if gap <= ABS_TOLERANCE or gap <= REL_TOLERANCE * max(vendor, gateway):
        return "match"
    return "over" if vendor > gateway else "under"


@router.post("")
async def reconcile(
    file: UploadFile = File(...),
    date_column: str = Form(""),
    cost_column: str = Form(""),
    model_column: str = Form(""),
    channel_ids: str = Form(""),
    utc_offset: int = Form(0, ge=-12, le=14),
    _: User = require_permission("stat:read"),
):
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="CSV larger than 10 MB")
    columns, rows = _read_csv(data)
    if not columns:
        raise HTTPException(status_code=400, detail="CSV has no header row")
    mapping = {
        "date": date_column or _guess(columns, "date"),
        "cost": cost_column or _guess(columns, "cost"),
        "model": model_column if model_column != "-" else "",
    }
    if not model_column:
        mapping["model"] = _guess(columns, "model")
    for field in ("date", "cost"):
        if mapping[field] not in columns:
            return {"columns": columns, "mapping": mapping, "error": f"missing_{field}_column", "rows": []}
    if mapping["model"] and mapping["model"] not in columns:
        mapping["model"] = ""

    vendor: dict[tuple[str, str], dict] = {}
    skipped = 0
    for row in rows:
        day = _parse_date(row.get(mapping["date"]) or "")
        cost = _parse_cost(row.get(mapping["cost"]) or "")
        if day is None or cost is None:
            skipped += 1
            continue
        model_raw = (row.get(mapping["model"]) or "").strip() if mapping["model"] else ""
        key = (day.isoformat(), _normalize_model(model_raw) if model_raw else "")
        bucket = vendor.setdefault(key, {"cost": Decimal(0), "names": set()})
        bucket["cost"] += cost
        if model_raw:
            bucket["names"].add(model_raw)
    if not vendor:
        return {"columns": columns, "mapping": mapping, "error": "no_rows", "rows": [], "skipped": skipped}

    days = sorted({day for day, _ in vendor})
    ids = [int(part) for part in channel_ids.split(",") if part.strip().isdigit()]
    by_model = bool(mapping["model"])
    gateway = await _gateway_totals(
        date.fromisoformat(days[0]), date.fromisoformat(days[-1]), ids, utc_offset, by_model,
    )

    result_rows = []
    total_vendor = Decimal(0)
    total_gateway = Decimal(0)
    for key in sorted(set(vendor) | set(gateway)):
        v = vendor.get(key, {"cost": Decimal(0), "names": set()})
        g = gateway.get(key, {"cost": Decimal(0), "requests": 0, "tokens": 0, "names": set()})
        total_vendor += v["cost"]
        total_gateway += g["cost"]
        diff = v["cost"] - g["cost"]
        result_rows.append({
            "date": key[0],
            "model": sorted(v["names"] or g["names"] or {key[1]})[0] if by_model else "",
            "vendor_cost": float(v["cost"]),
            "gateway_cost": float(g["cost"]),
            "diff": float(diff),
            "diff_pct": float(diff / g["cost"]) if g["cost"] else None,
            "requests": g["requests"],
            "tokens": g["tokens"],
            "status": _status(v["cost"], g["cost"]),
        })
    return {
        "columns": columns,
        "mapping": mapping,
        "skipped": skipped,
        "totals": {
            "vendor_cost": float(total_vendor),
            "gateway_cost": float(total_gateway),
            "diff": float(total_vendor - total_gateway),
            "mismatches": sum(1 for r in result_rows if r["status"] != "match"),
        },
        "rows": result_rows,
    }
