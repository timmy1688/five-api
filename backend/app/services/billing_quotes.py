"""Immutable per-request customer prices: model selling price x channel price multiplier."""
from decimal import Decimal, ROUND_CEILING

from fastapi import HTTPException

from app.models import ModelPrice
from app.services.pricing import catalog_prices, DEFAULT_MODEL_PRICES, USD_STEP

PUBLIC_PRICE_FIELDS = {"input": "prompt", "output": "completion", "cache_read": "cached",
                       "cache_write": "cache_write", "request": "request"}


def _unavailable(message: str) -> HTTPException:
    return HTTPException(503, {"error": {"type": "api_error", "code": "pricing_unavailable", "message": message}})


def quote_names(model: str, alias: str) -> list[str]:
    return [name for name in dict.fromkeys([alias, model]) if name]


async def price_rows(names) -> dict[str, ModelPrice]:
    names = list(names)
    return {row.model: row for row in await ModelPrice.filter(model__in=names)} if names else {}


def channel_override(channel, names: list[str]) -> dict | None:
    """A fixed customer price set on the channel, by public alias or upstream model name."""
    overrides = (getattr(channel, "price_overrides", None) or {}) if channel is not None else {}
    for name in names:
        raw = overrides.get(name)
        if raw is not None:
            prompt = raw.get("prompt", 0)
            return {
                "input": str(prompt), "output": str(raw.get("completion", 0)),
                "cache_read": str(raw.get("cached", 0)), "cache_write": str(raw.get("cache_write", prompt)),
                "request": str(raw.get("request", 0)),
            }
    return None


def pick_quote(model: str, names: list[str], rows: dict[str, ModelPrice], channel=None) -> dict:
    """The alias wins over the upstream name, so a mapped name can be sold at its own price.

    A disabled model price refuses the request even when the channel fixes a price.
    """
    row = next((rows[name] for name in names if name in rows), None)
    if row is not None and not row.is_active:
        raise _unavailable("Model selling price is disabled")
    override = channel_override(channel, names)
    if override is not None:
        return {"model": model, "source": "channel", "prices": override, "multiplier": "1"}
    if row is not None:
        source, prices = "global", {
            "input": str(row.prompt_price), "output": str(row.completion_price),
            "cache_read": str(row.cached_price), "cache_write": str(row.cache_write_price),
            "request": str(row.request_price),
        }
    else:
        catalog = next((name for name in names if name in DEFAULT_MODEL_PRICES), None)
        if catalog is None:
            raise _unavailable("Configure a selling price before using this model")
        raw = catalog_prices(catalog)
        source, prices = "catalog", {
            "input": str(raw["prompt"]), "output": str(raw["completion"]),
            "cache_read": str(raw["cached"]), "cache_write": str(raw["cache_write"]),
            "request": str(raw["request"]),
        }
    multiplier = Decimal(str(channel.price_multiplier)) if channel is not None else Decimal(1)
    return {"model": model, "source": source, "prices": prices, "multiplier": str(multiplier)}


async def selling_quote(model: str, alias: str = "", channel=None) -> dict:
    """Customer price for an upstream model reached through a public alias on one channel."""
    names = quote_names(model, alias)
    return pick_quote(model, names, await price_rows(names), channel)


def effective_prices(quote: dict) -> dict[str, float]:
    factor = Decimal(quote.get("multiplier", "1"))
    return {PUBLIC_PRICE_FIELDS[field]: float(Decimal(value) * factor) for field, value in quote["prices"].items()}


async def public_selling_prices(routes: dict[str, list[tuple]]) -> dict[str, dict]:
    """What a customer is billed per model on each channel, USD per 1M tokens or per request.

    routes maps each public model name to (channel, upstream model) pairs. A model with any
    unpriced route is left out because requests for it are refused. Top-level fields show the
    highest price across channels; `channels` lists each channel's own price.
    """
    rows = await price_rows({name for model, pairs in routes.items() for name in (model, *(a for _, a in pairs))})
    result = {}
    for model, pairs in routes.items():
        channels = []
        try:
            for channel, actual in pairs:
                prices = effective_prices(pick_quote(actual, quote_names(actual, model), rows, channel))
                channels.append({"channel_id": channel.id, "channel_name": channel.name, **prices})
        except HTTPException:
            continue
        if not channels:
            continue
        fields = PUBLIC_PRICE_FIELDS.values()
        prices = {field: max(entry[field] for entry in channels) for field in fields}
        prices["varies_by_route"] = any(
            any(entry[field] != channels[0][field] for field in fields) for entry in channels
        )
        result[model] = {**prices, "channels": channels}
    return result


async def snapshot_quotes(model: str, candidates: list | None) -> dict:
    if not candidates:
        return {"default": {"selling": await selling_quote(model)}}
    rows_by_names: dict[tuple[str, ...], dict] = {}
    snapshots = {}
    for channel, factory in candidates:
        target = getattr(factory, "serving_model", model)
        actual = (channel.model_mapping or {}).get(target, target)
        names = tuple(quote_names(actual, target))
        if names not in rows_by_names:
            rows_by_names[names] = await price_rows(names)
        snapshots[f"{channel.id}:{actual}"] = {
            "selling": pick_quote(actual, list(names), rows_by_names[names], channel),
        }
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
