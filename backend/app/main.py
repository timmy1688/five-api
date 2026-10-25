from contextlib import asynccontextmanager
import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from passlib.context import CryptContext
from tortoise.contrib.fastapi import RegisterTortoise

from app.config import settings, TORTOISE_ORM

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def init_admin():
    from app.models import User
    if not await User.exists(role="platform_admin"):
        await User.create(
            username=settings.INIT_ADMIN_USERNAME,
            hashed_password=pwd_context.hash(settings.INIT_ADMIN_PASSWORD),
            role="platform_admin", must_change_password=True,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with RegisterTortoise(
        app,
        config=TORTOISE_ORM,
        generate_schemas=False,
        add_exception_handlers=True,
    ):
        from app.utils.secrets import encrypt_plaintext_channel_keys, load_secret_key
        await load_secret_key()
        await encrypt_plaintext_channel_keys()
        await init_admin()
        from app.services.quota import quota_reset_loop
        from app.services.channel_health import health_check_loop
        from app.services.logging_service import log_cleanup_loop
        from app.services.metrics import ACTIVE_CHANNELS, ACTIVE_KEYS
        from app.services.settlements import recovery_loop
        from app.services.model_monitor import model_check_loop
        from app.models import Channel, APIKey
        ACTIVE_CHANNELS.set(await Channel.filter(is_enabled=True).count())
        ACTIVE_KEYS.set(await APIKey.filter(is_enabled=True).count())
        reset_task = asyncio.create_task(quota_reset_loop())
        health_task = asyncio.create_task(health_check_loop())
        cleanup_task = asyncio.create_task(log_cleanup_loop())
        settlement_task = asyncio.create_task(recovery_loop())
        monitor_task = asyncio.create_task(model_check_loop())
        tasks = (reset_task, health_task, cleanup_task, settlement_task, monitor_task)
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            from app.services.alerts import drain_alerts
            from app.services.ai_audit import drain_ai_reviews
            from app.services.settlements import recover_once
            try:
                async with asyncio.timeout(10):
                    await asyncio.gather(drain_alerts(), drain_ai_reviews())
                    await recover_once()
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Shutdown recovery incomplete; durable records remain for restart")
    from app.dependencies import close_redis
    from app.providers.base import close_http_clients

    await close_http_clients()
    await close_redis()


def _frontend_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "static"


def resolve_frontend_file(static_dir: Path, full_path: str) -> Path | None:
    """Map a URL path to a built frontend file.

    API prefixes stay 404 so a missing route is not replaced by the SPA.
    Unknown frontend paths return None and the caller serves index.html.
    """
    normalized = full_path.lstrip("/")
    if (
        normalized in {"metrics", "healthz"}
        or normalized.startswith(("api/", "v1/"))
        or normalized in {"docs", "redoc", "openapi.json"}
    ):
        raise LookupError(normalized)

    if not normalized:
        return None
    root = static_dir.resolve()
    candidate = (static_dir / normalized).resolve()
    if root == candidate or root not in candidate.parents:
        return None
    if candidate.is_file():
        return candidate
    return None


def _mount_frontend(app: FastAPI) -> None:
    static_dir = _frontend_dir()
    index = static_dir / "index.html"
    if not index.is_file():
        return

    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend(full_path: str):
        try:
            target = resolve_frontend_file(static_dir, full_path)
        except LookupError:
            raise HTTPException(status_code=404)
        if target is None:
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        headers = {}
        if full_path.startswith("assets/"):
            headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return FileResponse(target, headers=headers)


def create_app() -> FastAPI:
    app = FastAPI(title="Five API Gateway", version="0.4.0", lifespan=lifespan)
    from app.services.protocol_errors import install_error_handlers
    from app.services.redaction import configure_safe_logging
    install_error_handlers(app)
    configure_safe_logging()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.middleware.request_id import RequestIDMiddleware

    app.add_middleware(RequestIDMiddleware)

    from app.routers import (
        auth, channels, insights, keys, logs,
        model_groups, model_prices, models,
        stats, tenants, users,
        openai_proxy, anthropic_proxy, metrics,
    )

    app.include_router(openai_proxy.router)
    app.include_router(anthropic_proxy.router)
    app.include_router(auth.router)
    app.include_router(channels.router)
    app.include_router(keys.router)
    app.include_router(logs.router)
    app.include_router(model_groups.router)
    app.include_router(model_prices.router)
    app.include_router(models.router)
    from app.routers import model_checks
    app.include_router(model_checks.router)
    from app.routers import audit as audit_router
    from app.routers import security as security_router

    app.include_router(security_router.router)
    app.include_router(audit_router.router)
    from app.routers import settings as settings_router

    app.include_router(settings_router.router)
    app.include_router(stats.router)
    app.include_router(insights.router)
    app.include_router(tenants.router)
    app.include_router(users.router)
    app.include_router(metrics.router)
    from app.routers import settlements as settlement_router
    app.include_router(settlement_router.router)
    _mount_frontend(app)

    return app


app = create_app()
