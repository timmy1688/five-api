from typing import ClassVar

from pydantic import field_validator
from pydantic_settings import BaseSettings
from urllib.parse import quote


class Settings(BaseSettings):
    # JWT signing and upstream encryption use separate external secrets.
    SECRET_KEY: str = ""
    ENCRYPTION_KEY: str = ""
    SECRETS_FILE: str = "../data/secrets.json"
    JWT_ALGORITHM: ClassVar[str] = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "five"
    MYSQL_PASSWORD: str = "five_password"
    MYSQL_DATABASE: str = "five_api"
    # Each inference request runs a few dozen statements; the driver default of 5 connections queues concurrent calls.
    MYSQL_POOL_SIZE: int = 50

    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    INIT_ADMIN_USERNAME: str = "admin"
    INIT_ADMIN_PASSWORD: str = "admin123"

    CHANNEL_HEALTH_THRESHOLD: int = 3
    CHANNEL_HEALTH_CHECK_INTERVAL: int = 60
    LOG_RETENTION_DAYS: int = 90
    ALLOW_INSECURE_UPSTREAMS: bool = False

    STICKY_SESSION_ENABLED: bool = True
    STICKY_SESSION_TTL: int = 900

    @field_validator("SECRET_KEY", "ENCRYPTION_KEY")
    @classmethod
    def _long_secret(cls, value: str) -> str:
        value = value.strip()
        if value and len(value) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return value

    @property
    def database_url(self) -> str:
        return (
            f"mysql://{quote(self.MYSQL_USER, safe='')}:{quote(self.MYSQL_PASSWORD, safe='')}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{quote(self.MYSQL_DATABASE, safe='')}"
        )

    model_config = {
        "env_file": ("../.env", ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()

TORTOISE_ORM = {
    "connections": {
        "default": f"{settings.database_url}?minsize=5&maxsize={settings.MYSQL_POOL_SIZE}",
    },
    "apps": {
        "models": {
            "models": ["app.models", "aerich.models"],
            "default_connection": "default",
        },
    },
}
