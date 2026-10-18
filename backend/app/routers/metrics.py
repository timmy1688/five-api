import ipaddress
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from tortoise import connections

from app.config import settings
from app import dependencies
from app.utils.ip_check import get_client_ip

router = APIRouter(tags=["metrics"])


def _is_loopback(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


@router.get("/healthz")
async def healthz():
    """存活和就绪检查：MySQL 与 Redis 都能用才返回 200。"""
    checks = {}
    try:
        await connections.get("default").execute_query("SELECT 1")
        checks["mysql"] = "ok"
    except Exception:
        checks["mysql"] = "error"
    try:
        await (await dependencies.get_redis()).ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"
    healthy = all(value == "ok" for value in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "error", **checks},
    )


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request):
    """Prometheus 指标。设置 METRICS_TOKEN 后凭 Bearer 访问，否则只允许本机。

    渠道名和费用不能公开。反向代理和 Docker 端口转发会让外部请求看起来来自
    私网地址，所以不按私网放行。
    """
    token = settings.METRICS_TOKEN
    if token:
        supplied = request.headers.get("authorization", "")
        if not secrets.compare_digest(supplied.encode(), f"Bearer {token}".encode()):
            raise HTTPException(status_code=401, detail="Invalid metrics token")
    elif not _is_loopback(get_client_ip(request)):
        raise HTTPException(status_code=403, detail="Set METRICS_TOKEN to scrape metrics remotely")
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
