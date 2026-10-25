"""Immutable per-request selling prices and upstream cost estimates."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING

from fastapi import HTTPException

from app.models import ModelPrice
from app.services.pricing import catalog_prices, DEFAULT_MODEL_PRICES, find_channel_pricing, USD_STEP
from app.services.settings_service import gateway_config
from app.services import time_pricing


async def selling_quote(model: str, alias: str = "") -> dict:
    names = [name for name in dict.fromkeys([model, alias]) if name]
    for name in names:
        if not name:
            continue
        row = await ModelPrice.get_or_none(model=name)
        if row:
            if not row.is_active:
                raise HTTPException(503, {"error": {"type": "api_error", "code": "pricing_unavailable",
                                                   "message": "Model selling price is disabled"}})
            return {"model": model, "source": "global", "prices": {
                "input": str(row.prompt_price), "output": str(row.completion_price),
                "cache_read": str(row.cached_price), "cache_write": str(row.cache_write_price),
                "request": str(row.request_price),
            }, "multiplier": str(row.multiplier)}
    for name in names:
        if name in DEFAULT_MODEL_PRICES:
            raw = catalog_prices(name)
            return {"model": model, "source": "catalog", "prices": {
                "input": str(raw["prompt"]), "output": str(raw["completion"]),
                "cache_read": str(raw["cached"]), "cache_write": str(raw["cache_write"]),
                "request": str(raw["request"]),
            }, "multiplier": "1"}
    raise HTTPException(503, {"error": {"type": "api_error", "code": "pricing_unavailable",
                                       "message": "Configure a global selling price before using this model"}})


async def snapshot_quotes(model: str, candidates: list | None) -> dict:
    snapshots = {}
    rules = (await gateway_config())["time_pricing"]
    now = datetime.now(timezone.utc)
    if not candidates:
        snapshots["default"] = {"selling": await selling_quote(model), "upstream": None}
        return snapshots
    for channel, factory in candidates:
        target = getattr(factory, "serving_model", model)
        actual = (channel.model_mapping or {}).get(target, target)
        selling = await selling_quote(actual, target)
        upstream = dict(selling)
        raw = find_channel_pricing(actual, channel.model_pricing, channel.model_mapping)
        if raw is not None:
            upstream = {"model": actual, "source": "channel", "prices": {
                "input": str(raw.get("prompt", 0)), "output": str(raw.get("completion", 0)),
                "cache_read": str(raw.get("cached", 0)),
                "cache_write": str(raw.get("cache_write", raw.get("prompt", 0))),
                "request": str(raw.get("request", selling["prices"]["request"])),
            }, "multiplier": "1"}
        else:
            upstream["source"] = "selling_price_estimate"
        rule = time_pricing.match_rule(rules, actual, channel.id, now)
        upstream["channel_multiplier"] = str(channel.cost_multiplier)
        upstream["multiplier"] = str(channel.cost_multiplier * Decimal(str(rule["multiplier"] if rule else 1)))
        snapshots[f"{channel.id}:{actual}"] = {"selling": selling, "upstream": upstream}
    return snapshots


def estimate_quotes(quotes: dict, input_tokens: int, output_tokens: int, request_units: int) -> Decimal:
    values = []
    for snapshot in quotes.values():
        prices = {key: Decimal(value) for key, value in snapshot["selling"]["prices"].items()}
        cost = (Decimal(input_tokens) * max(prices["input"], prices["cache_write"], prices["cache_read"]) +
                Decimal(output_tokens) * prices["output"]) / 1_000_000
        values.append((cost + Decimal(request_units) * prices["request"]) * Decimal(snapshot["selling"].get("multiplier", "1")))
    return max(values, default=Decimal(0)).quantize(USD_STEP, rounding=ROUND_CEILING)


def quote_cost(quote: dict, prompt: int, output: int, cache_read: int, cache_write: int, request_units: int) -> dict:
    if min(prompt, output, cache_read, cache_write, request_units) < 0:
        raise ValueError("Invalid upstream token usage")
    prices = {key: Decimal(value) for key, value in quote["prices"].items()}
    fresh = max(prompt - cache_read - cache_write, 0)
    counts = {"input": fresh, "output": output, "cache_read": cache_read, "cache_write": cache_write}
    multiplier = Decimal(quote.get("multiplier", "1"))
    lines = {key: Decimal(value) * prices[key] * multiplier / 1_000_000 for key, value in counts.items()}
    lines["request"] = Decimal(request_units) * prices["request"] * multiplier
    savings = (Decimal(cache_read) * (prices["input"] - prices["cache_read"]) -
               Decimal(cache_write) * (prices["cache_write"] - prices["input"])) * multiplier / 1_000_000
    return {"cost": sum(lines.values(), Decimal(0)).quantize(USD_STEP),
            "cache_savings": savings.quantize(USD_STEP),
            "detail": {"model": quote["model"], "price_source": quote["source"], "prices": quote["prices"],
                       "tokens": {**counts, "request_units": request_units},
                       "lines": {key: str(value.quantize(USD_STEP)) for key, value in lines.items()},
                       "multiplier": str(multiplier)}}
