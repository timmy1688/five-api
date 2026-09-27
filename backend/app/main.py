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


async def init_roles():
    from app.models import Role
    from app.services.auth import BUILTIN_ROLES

    for role_def in BUILTIN_ROLES:
        existing = await Role.get_or_none(name=role_def["name"])
        if existing:
            if existing.permissions != role_def["permissions"]:
                existing.permissions = role_def["permissions"]
                existing.description = role_def["description"]
                await existing.save()
        else:
            await Role.create(
                name=role_def["name"],
                description=role_def["description"],
                permissions=role_def["permissions"],
                is_builtin=True,
            )


async def init_admin():
    from app.models import User, Role

    count = await User.all().count()
    if count == 0:
        super_admin_role = await Role.get(name="Super Admin")
        hashed = pwd_context.hash(settings.INIT_ADMIN_PASSWORD)
        await User.create(
            username=settings.INIT_ADMIN_USERNAME,
            hashed_password=hashed,
            role=super_admin_role,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with RegisterTortoise(
        app,
        config=TORTOISE_ORM,
        generate_schemas=False,
        add_exception_handlers=True,
    ):
        from app.utils.secrets import encrypt_plaintext_channel_keys
        await encrypt_plaintext_channel_keys()
        await init_roles()
        await init_admin()
        from app.services.quota import quota_reset_loop
        from app.services.channel_health import health_check_loop
        from app.services.logging_service import log_cleanup_loop
        from app.services.metrics import ACTIVE_CHANNELS, ACTIVE_KEYS
        from app.models import Channel, APIKey
        ACTIVE_CHANNELS.set(await Channel.filter(is_enabled=True).count())
        ACTIVE_KEYS.set(await APIKey.filter(is_enabled=True).count())
        reset_task = asyncio.create_task(quota_reset_loop())
        health_task = asyncio.create_task(health_check_loop())
        cleanup_task = asyncio.create_task(log_cleanup_loop())
        yield
        reset_task.cancel()
        health_task.cancel()
        cleanup_task.cancel()
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
        normalized == "metrics"
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
    app = FastAPI(title="Five API Gateway", version="0.1.0", lifespan=lifespan)

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
        auth, channels, keys, logs,
        model_groups, model_prices, models,
        roles, stats, users,
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
    app.include_router(roles.router)
    from app.routers import audit as audit_router
    from app.routers import security as security_router

    app.include_router(security_router.router)
    app.include_router(audit_router.router)
    from app.routers import settings as settings_router

    app.include_router(settings_router.router)
    app.include_router(stats.router)
    app.include_router(users.router)
    app.include_router(metrics.router)
    _mount_frontend(app)

    return app


app = create_app()
