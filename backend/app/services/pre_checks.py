from fastapi import HTTPException

from app.models import APIKey
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


async def run_pre_checks(api_key: APIKey, model: str, raise_error=openai_error) -> None:
    if not await check_quota(api_key):
        raise_error(429, "rate_limit_error", "quota_exceeded", "Spending quota exceeded")

    if api_key.allowed_models and model not in api_key.allowed_models:
        raise_error(403, "invalid_request_error", "model_not_allowed", f"Model {model} not allowed for this key")

    try:
        await rate_limiter.check_rpm(api_key.id, api_key.rpm_limit)
    except RPMExceeded:
        raise_error(429, "rate_limit_error", "rpm_limit", "Requests per minute limit exceeded")
