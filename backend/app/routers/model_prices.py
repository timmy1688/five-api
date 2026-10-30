from app.services.management_events import audit_mutation
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models import User, Channel, ModelPrice
from app.schemas.model_price import ModelPriceCreate, ModelPriceResponse, ModelPriceUpdate
from app.services.auth import require_platform_admin
from app.services.pricing import DEFAULT_MODEL_PRICES, MODEL_PRICE_CATALOG_VERSION, catalog_prices

router = APIRouter(prefix="/api/model-prices", tags=["model-prices"])


def _to_response(mp: ModelPrice) -> ModelPriceResponse:
    return ModelPriceResponse(
        id=mp.id,
        model=mp.model,
        prompt_price=float(mp.prompt_price),
        completion_price=float(mp.completion_price),
        cached_price=float(mp.cached_price),
        cache_write_price=float(mp.cache_write_price),
        request_price=float(mp.request_price),
        currency=mp.currency,
        is_active=mp.is_active,
        created_at=mp.created_at,
        updated_at=mp.updated_at,
    )


@router.get("")
async def list_model_prices(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    _: User = Depends(require_platform_admin),
):
    total = await ModelPrice.all().count()
    items = await ModelPrice.all().order_by("model").offset((page - 1) * size).limit(size)
    return {"total": total, "items": [_to_response(mp) for mp in items]}


@router.get("/defaults")
async def get_defaults(_: User = Depends(require_platform_admin)):
    return [
        {"model": model, **catalog_prices(model)}
        for model in sorted(DEFAULT_MODEL_PRICES)
    ]


@router.get("/unpriced")
async def get_unpriced_models(_: User = Depends(require_platform_admin)):
    channels = await Channel.all().values("id", "name", "models", "model_mapping", "price_overrides")
    priced_models = set()
    for mp in await ModelPrice.filter(is_active=True).values_list("model", flat=True):
        priced_models.add(mp)
    inactive = set(await ModelPrice.filter(is_active=False).values_list("model", flat=True))
    priced_models |= set(DEFAULT_MODEL_PRICES) - inactive

    unpriced: dict[str, list[str]] = {}
    for ch in channels:
        mapping = ch["model_mapping"] or {}
        fixed = set(ch["price_overrides"] or {})
        for model in (ch["models"] or []):
            actual = mapping.get(model, model)
            if not {actual, model} & (priced_models | fixed):
                unpriced.setdefault(model, []).append(ch["name"])

    return [
        {"model": model, "channels": ch_names}
        for model, ch_names in sorted(unpriced.items())
    ]


@router.post("/sync-defaults")
@audit_mutation("price.sync")
async def sync_defaults(
    _: User = Depends(require_platform_admin),
):
    created = unchanged = 0
    for model in DEFAULT_MODEL_PRICES:
        prices = catalog_prices(model)
        _, inserted = await ModelPrice.get_or_create(model=model, defaults={
            "prompt_price": prices["prompt"], "completion_price": prices["completion"],
            "cached_price": prices["cached"], "cache_write_price": prices["cache_write"],
            "request_price": prices["request"],
        })
        created += int(inserted)
        unchanged += int(not inserted)
    return {
        "message": "Missing reference prices added; existing prices preserved",
        "created": created, "updated": 0, "unchanged": unchanged,
        "total": len(DEFAULT_MODEL_PRICES), "catalog_version": MODEL_PRICE_CATALOG_VERSION,
    }


@router.post("", response_model=ModelPriceResponse, status_code=status.HTTP_201_CREATED)
@audit_mutation("price.create")
async def create_model_price(body: ModelPriceCreate, _: User = Depends(require_platform_admin)):
    existing = await ModelPrice.get_or_none(model=body.model)
    if existing:
        raise HTTPException(status_code=409, detail=f"Price for model '{body.model}' already exists")
    data = body.model_dump()
    if data["cache_write_price"] is None:
        data["cache_write_price"] = data["prompt_price"]
    mp = await ModelPrice.create(**data)
    return _to_response(mp)


@router.get("/{price_id}", response_model=ModelPriceResponse)
async def get_model_price(price_id: int, _: User = Depends(require_platform_admin)):
    mp = await ModelPrice.get_or_none(id=price_id)
    if mp is None:
        raise HTTPException(status_code=404, detail="Model price not found")
    return _to_response(mp)


@router.put("/{price_id}", response_model=ModelPriceResponse)
@audit_mutation("price.update")
async def update_model_price(price_id: int, body: ModelPriceUpdate, _: User = Depends(require_platform_admin)):
    mp = await ModelPrice.get_or_none(id=price_id)
    if mp is None:
        raise HTTPException(status_code=404, detail="Model price not found")
    update_data = body.model_dump(exclude_unset=True, exclude_none=True)
    if update_data:
        await ModelPrice.filter(id=price_id).update(**update_data)
        mp = await ModelPrice.get(id=price_id)
    return _to_response(mp)


@router.delete("/{price_id}")
@audit_mutation("price.delete")
async def delete_model_price(price_id: int, _: User = Depends(require_platform_admin)):
    deleted = await ModelPrice.filter(id=price_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Model price not found")
    return {"message": "Deleted"}
