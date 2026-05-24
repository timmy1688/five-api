from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from tortoise.contrib.fastapi import RegisterTortoise

from app.config import settings, TORTOISE_ORM

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def init_admin():
    from app.models import Admin

    count = await Admin.all().count()
    if count == 0:
        hashed = pwd_context.hash(settings.INIT_ADMIN_PASSWORD)
        await Admin.create(
            username=settings.INIT_ADMIN_USERNAME,
            hashed_password=hashed,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with RegisterTortoise(
        app,
        config=TORTOISE_ORM,
        generate_schemas=True,
        add_exception_handlers=True,
    ):
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
    await close_redis()


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

    from app.routers import admin_auth, admin_channels, admin_keys, admin_logs, admin_model_prices, admin_models, admin_stats, admin_users, openai_proxy, anthropic_proxy, metrics

    app.include_router(openai_proxy.router)
    app.include_router(anthropic_proxy.router)
    app.include_router(admin_auth.router)
    app.include_router(admin_channels.router)
    app.include_router(admin_keys.router)
    app.include_router(admin_logs.router)
    app.include_router(admin_model_prices.router)
    app.include_router(admin_models.router)
    app.include_router(admin_stats.router)
    app.include_router(admin_users.router)
    app.include_router(metrics.router)

    return app


app = create_app()
