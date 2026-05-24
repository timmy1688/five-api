from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus 指标端点，无需认证。"""
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
