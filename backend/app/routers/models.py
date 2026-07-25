from fastapi import APIRouter, Depends

from app.models import User, Channel, ModelPrice
from app.services.auth import require_permission
from app.services.pricing import find_channel_pricing

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("")
async def list_models(_: User = require_permission("channel:read")):
    channels = await Channel.filter(is_enabled=True).values(
        "id", "name", "provider", "models", "model_mapping", "model_pricing",
    )
    prices = {
        mp.model: {"prompt": float(mp.prompt_price), "completion": float(mp.completion_price), "cached": float(mp.cached_price)}
        for mp in await ModelPrice.filter(is_active=True)
    }

    model_map: dict[str, dict] = {}
    for ch in channels:
        ch_pricing = ch["model_pricing"] or {}
        mapping = ch["model_mapping"] or {}
        for model in (ch["models"] or []):
            if model not in model_map:
                model_map[model] = {
                    "model": model,
                    "channels": [],
                    "providers": set(),
                    "channel_prices": [],
                }
            entry = model_map[model]
            actual = mapping.get(model, model)
            channel_price = find_channel_pricing(actual, ch_pricing, mapping)
            source = "channel"
            if channel_price is None:
                channel_price = prices.get(actual) or prices.get(model)
                source = "global" if channel_price is not None else "unpriced"
            if channel_price is not None:
                channel_price = {
                    "prompt": float(channel_price.get("prompt", 0)),
                    "completion": float(channel_price.get("completion", 0)),
                    "cached": float(channel_price.get("cached", 0)),
                }
            entry["channels"].append({
                "id": ch["id"],
                "name": ch["name"],
                "provider": ch["provider"],
                "pricing": channel_price,
                "pricing_source": source,
            })
            entry["channel_prices"].append(channel_price)
            entry["providers"].add(ch["provider"])

    result = []
    for m in sorted(model_map.values(), key=lambda x: x["model"]):
        variants = {
            (
                p["prompt"],
                p["completion"],
                p["cached"],
            )
            if p is not None else None
            for p in m.pop("channel_prices")
        }
        pricing_varies = len(variants) > 1
        pricing = None
        if len(variants) == 1 and None not in variants:
            prompt, completion, cached = next(iter(variants))
            pricing = {
                "prompt": prompt,
                "completion": completion,
                "cached": cached,
            }
        result.append({
            "model": m["model"],
            "providers": sorted(m["providers"]),
            "channel_count": len(m["channels"]),
            "channels": m["channels"],
            "pricing": pricing,
            "pricing_varies": pricing_varies,
            "has_pricing": any(ch["pricing"] is not None for ch in m["channels"]),
        })
    return {"total": len(result), "items": result}
