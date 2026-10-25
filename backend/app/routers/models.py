from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from tortoise.functions import Max

from app.models import User, Channel, ModelProbe
from app.services.auth import require_platform_admin
from app.services.billing_quotes import selling_quote
from app.services.model_checks import supports_capability
from app.services.pricing import find_channel_pricing
from app.services.model_monitor import latest_probes, next_check, supports_health
from app.services.settings_service import gateway_config

router = APIRouter(prefix="/api/models", tags=["models"])


def effective_prices(quote):
    if quote is None:
        return None
    factor = Decimal(quote.get("multiplier", "1"))
    return {name: float(Decimal(value) * factor) for name, value in quote["prices"].items()}


def brief_probe(record):
    if not record:
        return None
    return {key: getattr(record, key) for key in ("id", "status", "latency_ms", "score", "created_at", "run_source")}


@router.get("")
async def list_models(_: User = Depends(require_platform_admin)):
    channels = await Channel.filter(is_enabled=True)
    probes = await latest_probes()
    schedule = (await gateway_config())["model_checks"]
    result = {}
    quotes = {}
    for channel in channels:
        mapping = channel.model_mapping or {}
        for model in channel.models or []:
            actual = mapping.get(model, model)
            pair = (actual, model)
            if pair not in quotes:
                try:
                    quotes[pair] = await selling_quote(actual, model)
                except HTTPException:
                    quotes[pair] = None
            quote = quotes[pair]
            effective = effective_prices(quote)
            pricing = None if effective is None else {
                "prompt": effective["input"], "completion": effective["output"],
                "cached": effective["cache_read"], "cache_write": effective["cache_write"],
                "request": effective["request"],
            }
            upstream = find_channel_pricing(actual, channel.model_pricing, mapping)
            factor = float(channel.cost_multiplier)
            if upstream is None:
                upstream_source = "selling_price_estimate"
                upstream = None if quote is None else {
                    "prompt": float(quote["prices"]["input"]), "completion": float(quote["prices"]["output"]),
                    "cached": float(quote["prices"]["cache_read"]), "cache_write": float(quote["prices"]["cache_write"]),
                    "request": float(quote["prices"]["request"]),
                }
            else:
                upstream_source = "channel"
                upstream = {**upstream, "cache_write": upstream.get("cache_write", upstream.get("prompt", 0))}
            upstream = {name: float(value) * factor for name, value in upstream.items()} if upstream else None
            health_record = probes.get((channel.id, model, actual, "health"))
            capability_record = probes.get((channel.id, model, actual, "capability"))
            health = brief_probe(health_record)
            capability = brief_probe(capability_record)
            entry = result.setdefault(model, {"model": model, "channels": [], "providers": set()})
            entry["providers"].add(channel.provider)
            entry["channels"].append({
                "id": channel.id, "name": channel.name, "provider": channel.provider, "actual_model": actual,
                "pricing": pricing, "pricing_source": quote["source"] if quote else "unpriced",
                "multiplier": float(quote["multiplier"]) if quote else None,
                "upstream_cost": upstream, "upstream_source": upstream_source, "cost_multiplier": factor,
                "health": health, "capability": capability, "capability_supported": supports_capability(actual),
                "health_supported": supports_health(actual),
                "next_health_at": next_check(health_record, schedule["health_interval_seconds"]) if schedule["health_enabled"] else None,
                "next_capability_at": next_check(capability_record, schedule["capability_interval_seconds"]) if schedule["capability_enabled"] and supports_capability(actual) else None,
            })
    items = []
    for model in sorted(result):
        entry = result[model]
        variants = {tuple(sorted(channel["pricing"].items())) if channel["pricing"] else None for channel in entry["channels"]}
        pricing = dict(next(iter(variants))) if len(variants) == 1 and None not in variants else None
        states = [channel["health"]["status"] for channel in entry["channels"] if channel["health"]]
        health = "healthy" if "healthy" in states else "unavailable" if len(states) == len(entry["channels"]) else "unknown"
        items.append({
            **entry, "providers": sorted(entry["providers"]), "channel_count": len(entry["channels"]),
            "pricing": pricing, "pricing_varies": len(variants) > 1,
            "has_pricing": all(channel["pricing"] is not None for channel in entry["channels"]),
            "health": health,
        })
    return {"total": len(items), "items": items}
