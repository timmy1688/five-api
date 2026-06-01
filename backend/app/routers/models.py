from fastapi import APIRouter, Depends

from app.models import User, Channel, ModelPrice
from app.services.auth import require_permission

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
                model_map[model] = {"model": model, "channels": [], "providers": set(), "pricing": None}
            entry = model_map[model]
            entry["channels"].append({"id": ch["id"], "name": ch["name"], "provider": ch["provider"]})
            entry["providers"].add(ch["provider"])
            if entry["pricing"] is None:
                if model in ch_pricing:
                    entry["pricing"] = ch_pricing[model]
                else:
                    actual = mapping.get(model, model)
                    if actual in prices:
                        entry["pricing"] = prices[actual]
                    elif model in prices:
                        entry["pricing"] = prices[model]

    result = []
    for m in sorted(model_map.values(), key=lambda x: x["model"]):
        result.append({
            "model": m["model"],
            "providers": sorted(m["providers"]),
            "channel_count": len(m["channels"]),
            "channels": m["channels"],
            "pricing": m["pricing"],
        })
    return {"total": len(result), "items": result}
