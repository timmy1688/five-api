from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models import User, Channel, ModelPrice
from app.schemas.model_price import ModelPriceCreate, ModelPriceResponse, ModelPriceUpdate
from app.services.auth import require_permission
from app.services.pricing import DEFAULT_MODEL_PRICES

router = APIRouter(prefix="/api/model-prices", tags=["model-prices"])


def _to_response(mp: ModelPrice) -> ModelPriceResponse:
    return ModelPriceResponse(
        id=mp.id,
        model=mp.model,
        prompt_price=float(mp.prompt_price),
        completion_price=float(mp.completion_price),
        cached_price=float(mp.cached_price),
        currency=mp.currency,
        is_active=mp.is_active,
        created_at=mp.created_at,
        updated_at=mp.updated_at,
    )


@router.get("")
async def list_model_prices(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    _: User = require_permission("model_price:read"),
):
    total = await ModelPrice.all().count()
    items = await ModelPrice.all().order_by("model").offset((page - 1) * size).limit(size)
    return {"total": total, "items": [_to_response(mp) for mp in items]}


@router.get("/defaults")
async def get_defaults(_: User = require_permission("model_price:read")):
    return [
        {"model": model, **prices}
        for model, prices in sorted(DEFAULT_MODEL_PRICES.items())
    ]


@router.get("/unpriced")
async def get_unpriced_models(_: User = require_permission("model_price:read")):
    channels = await Channel.all().values("id", "name", "models", "model_mapping", "model_pricing")
    priced_models = set()
    for mp in await ModelPrice.filter(is_active=True).values_list("model", flat=True):
        priced_models.add(mp)

    unpriced: dict[str, list[str]] = {}
    for ch in channels:
        mapping = ch["model_mapping"] or {}
        ch_pricing = ch["model_pricing"] or {}
        for model in (ch["models"] or []):
            actual = mapping.get(model, model)
            if actual not in priced_models and model not in priced_models and model not in ch_pricing and actual not in ch_pricing:
                unpriced.setdefault(model, []).append(ch["name"])

    return [
        {"model": model, "channels": ch_names}
        for model, ch_names in sorted(unpriced.items())
    ]


@router.post("/sync-defaults")
async def sync_defaults(_: User = require_permission("model_price:write")):
    created = 0
    for model, prices in DEFAULT_MODEL_PRICES.items():
        existing = await ModelPrice.get_or_none(model=model)
        if not existing:
            await ModelPrice.create(
                model=model,
                prompt_price=prices["prompt"],
                completion_price=prices["completion"],
                cached_price=prices.get("cached", 0),
            )
            created += 1
    return {"message": f"Synced {created} new model prices", "created": created}


@router.post("", response_model=ModelPriceResponse, status_code=status.HTTP_201_CREATED)
async def create_model_price(body: ModelPriceCreate, _: User = require_permission("model_price:write")):
    existing = await ModelPrice.get_or_none(model=body.model)
    if existing:
        raise HTTPException(status_code=409, detail=f"Price for model '{body.model}' already exists")
    mp = await ModelPrice.create(**body.model_dump())
    return _to_response(mp)


@router.get("/{price_id}", response_model=ModelPriceResponse)
async def get_model_price(price_id: int, _: User = require_permission("model_price:read")):
    mp = await ModelPrice.get_or_none(id=price_id)
    if mp is None:
        raise HTTPException(status_code=404, detail="Model price not found")
    return _to_response(mp)


@router.put("/{price_id}", response_model=ModelPriceResponse)
async def update_model_price(price_id: int, body: ModelPriceUpdate, _: User = require_permission("model_price:write")):
    mp = await ModelPrice.get_or_none(id=price_id)
    if mp is None:
        raise HTTPException(status_code=404, detail="Model price not found")
    update_data = body.model_dump(exclude_unset=True)
    if update_data:
        await ModelPrice.filter(id=price_id).update(**update_data)
        mp = await ModelPrice.get(id=price_id)
    return _to_response(mp)


@router.delete("/{price_id}")
async def delete_model_price(price_id: int, _: User = require_permission("model_price:write")):
    deleted = await ModelPrice.filter(id=price_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Model price not found")
    return {"message": "Deleted"}
