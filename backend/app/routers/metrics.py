import ipaddress
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from tortoise import connections

from app import dependencies
from app.services.settings_service import metrics_token
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
    """Prometheus 指标。本机直接访问，远程凭「系统设置」里的令牌以 Bearer 访问。

    渠道名和费用不能公开。反向代理和 Docker 端口转发会让外部请求看起来来自
    私网地址，所以不按私网放行。
    """
    supplied = request.headers.get("authorization", "")
    if supplied:
        expected = f"Bearer {await metrics_token()}"
        if not secrets.compare_digest(supplied.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="Invalid metrics token")
    elif not _is_loopback(get_client_ip(request)):
        raise HTTPException(
            status_code=403, detail="Use the metrics token from System Settings to scrape remotely"
        )
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
