"""Compare a vendor bill CSV with what the gateway billed for the same days.

Vendor exports differ, so the caller maps three columns: date, cost and an
optional model. Gateway totals come from request logs grouped by the actual
upstream model, which is the name vendors bill by. Log retention bounds how
far back a bill can be checked.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from tortoise import connections

MAX_ROWS = 200_000
# A gap counts as a mismatch when it passes both limits.
ABS_TOLERANCE = Decimal("0.01")
REL_TOLERANCE = Decimal("0.05")
NO_MODEL = "-"

_GUESSES = {
    "date": ("date", "day", "usage_date", "time", "timestamp", "start_time", "日期", "时间"),
    "model": ("model", "model_name", "model_id", "sku", "product", "模型"),
    "cost": ("cost", "cost_usd", "amount", "amount_usd", "usd", "total_cost", "price", "费用", "金额"),
}
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y")

Key = tuple[str, str]


@dataclass
class _Bucket:
    cost: Decimal = Decimal(0)
    requests: int = 0
    tokens: int = 0
    names: set[str] = field(default_factory=set)


def _normalize_model(name: str) -> str:
    return re.sub(r"[\s_.]+", "-", name.strip().lower())


def _guess(columns: list[str], kind: str) -> str:
    lowered = {c.strip().lower(): c for c in columns}
    for candidate in _GUESSES[kind]:
        if candidate in lowered:
            return lowered[candidate]
    for column in columns:
        if any(candidate in column.lower() for candidate in _GUESSES[kind]):
            return column
    return ""


def _parse_date(raw: str) -> date | None:
    value = (raw or "").strip()
    if not value:
        return None
    if value.isdigit() and len(value) >= 10:
        return datetime.fromtimestamp(int(value[:10]), tz=timezone.utc).date()
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


def read_csv(data: bytes) -> tuple[list[str], list[dict]]:
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    columns = [c for c in (reader.fieldnames or []) if c is not None]
    rows = [row for _, row in zip(range(MAX_ROWS), reader)]
    return columns, rows


def resolve_mapping(columns: list[str], date_column: str, cost_column: str, model_column: str) -> dict:
    """Empty means guess. NO_MODEL compares per day only."""
    mapping = {
        "date": date_column or _guess(columns, "date"),
        "cost": cost_column or _guess(columns, "cost"),
        "model": "" if model_column == NO_MODEL else (model_column or _guess(columns, "model")),
    }
    if mapping["model"] not in columns:
        mapping["model"] = ""
    return mapping


def _vendor_totals(rows: list[dict], mapping: dict) -> tuple[dict[Key, _Bucket], int]:
    totals: dict[Key, _Bucket] = {}
    skipped = 0
    for row in rows:
        day = _parse_date(row.get(mapping["date"]) or "")
        cost = _parse_cost(row.get(mapping["cost"]) or "")
        if day is None or cost is None:
            skipped += 1
            continue
        model = (row.get(mapping["model"]) or "").strip() if mapping["model"] else ""
        bucket = totals.setdefault((day.isoformat(), _normalize_model(model)), _Bucket())
        bucket.cost += cost
        if model:
            bucket.names.add(model)
    return totals, skipped


async def _gateway_totals(
    start: date, end: date, channel_ids: list[int], utc_offset: int, by_model: bool,
) -> dict[Key, _Bucket]:
    conn = connections.get("default")
    sqlite = conn.capabilities.dialect == "sqlite"
    mark = "?" if sqlite else "%s"
    if sqlite:
        day_expr = f"date(datetime(created_at, '{utc_offset:+d} hours'))"
    else:
        day_expr = f"DATE(DATE_ADD(created_at, INTERVAL {utc_offset} HOUR))"
    model_expr = "model_actual" if by_model else "''"
    shift = timedelta(hours=utc_offset)
    since = datetime.combine(start, datetime.min.time()) - shift
    until = datetime.combine(end + timedelta(days=1), datetime.min.time()) - shift
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
    totals: dict[Key, _Bucket] = {}
    for r in await conn.execute_query_dict(sql, params):
        model = r["m"] or ""
        bucket = totals.setdefault((str(r["d"])[:10], _normalize_model(model)), _Bucket())
        bucket.cost += Decimal(str(r["c"] or 0))
        bucket.requests += int(r["n"] or 0)
        bucket.tokens += int(r["p"] or 0) + int(r["o"] or 0)
        if model:
            bucket.names.add(model)
    return totals


def _status(vendor: Decimal, gateway: Decimal) -> str:
    gap = abs(vendor - gateway)
    if gap <= ABS_TOLERANCE or gap <= REL_TOLERANCE * max(vendor, gateway):
        return "match"
    return "over" if vendor > gateway else "under"


def _compare(vendor: dict[Key, _Bucket], gateway: dict[Key, _Bucket], by_model: bool) -> list[dict]:
    rows = []
    for key in sorted(set(vendor) | set(gateway)):
        v, g = vendor.get(key, _Bucket()), gateway.get(key, _Bucket())
        diff = v.cost - g.cost
        rows.append({
            "date": key[0],
            "model": sorted(v.names or g.names or {key[1]})[0] if by_model else "",
            "vendor_cost": float(v.cost),
            "gateway_cost": float(g.cost),
            "diff": float(diff),
            "diff_pct": float(diff / g.cost) if g.cost else None,
            "requests": g.requests,
            "tokens": g.tokens,
            "status": _status(v.cost, g.cost),
        })
    return rows


async def reconcile_bill(
    columns: list[str], rows: list[dict], mapping: dict, channel_ids: list[int], utc_offset: int,
) -> dict:
    result: dict = {"columns": columns, "mapping": mapping, "rows": []}
    for kind in ("date", "cost"):
        if mapping[kind] not in columns:
            return {**result, "error": f"missing_{kind}_column"}
    vendor, skipped = _vendor_totals(rows, mapping)
    result["skipped"] = skipped
    if not vendor:
        return {**result, "error": "no_rows"}

    days = sorted(day for day, _ in vendor)
    by_model = bool(mapping["model"])
    gateway = await _gateway_totals(
        date.fromisoformat(days[0]), date.fromisoformat(days[-1]), channel_ids, utc_offset, by_model,
    )
    compared = _compare(vendor, gateway, by_model)
    vendor_cost = sum((b.cost for b in vendor.values()), Decimal(0))
    gateway_cost = sum((b.cost for b in gateway.values()), Decimal(0))
    return {
        **result,
        "rows": compared,
        "totals": {
            "vendor_cost": float(vendor_cost),
            "gateway_cost": float(gateway_cost),
            "diff": float(vendor_cost - gateway_cost),
            "mismatches": sum(1 for r in compared if r["status"] != "match"),
        },
    }
