from fastapi import HTTPException

from app.models import APIKey, ModelGroup
from app.services.quota import check_quota
from app.services.rate_limit import RPMExceeded, rate_limiter


def openai_error(status_code: int, error_type: str, code: str, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"error": {"message": message, "type": error_type, "code": code}},
    )


def anthropic_error(status_code: int, error_type: str, code: str, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"type": "error", "error": {"type": error_type, "message": message}},
    )


async def get_effective_allowed_models(api_key: APIKey) -> list[str]:
    """返回 Key 的有效模型白名单。优先级：model_group > allowed_models > 空（不限制）。"""
    if api_key.model_group_id:
        group = await ModelGroup.get_or_none(id=api_key.model_group_id)
        if group:
            return group.models or []
    return api_key.allowed_models or []


async def run_pre_checks(api_key: APIKey, model: str, raise_error=openai_error) -> None:
    """统一前置检查管线：quota → model_access → RPM。"""
    if not await check_quota(api_key):
        raise_error(429, "rate_limit_error", "quota_exceeded", "Spending quota exceeded")

    effective_models = await get_effective_allowed_models(api_key)
    if effective_models and model not in effective_models:
        raise_error(403, "invalid_request_error", "model_not_allowed", f"Model {model} not allowed for this key")

    try:
        await rate_limiter.check_rpm(api_key.id, api_key.rpm_limit)
    except RPMExceeded:
        raise_error(429, "rate_limit_error", "rpm_limit", "Requests per minute limit exceeded")
