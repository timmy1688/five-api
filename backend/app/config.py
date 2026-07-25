import os
import secrets
from pathlib import Path
from typing import ClassVar

from pydantic_settings import BaseSettings


_SECRET_FILE = Path(__file__).resolve().parents[2] / "data" / ".secret_key"


def _persistent_secret(configured: str) -> str:
    """Load one stable application secret, creating it on first startup."""
    if _SECRET_FILE.is_file():
        return _SECRET_FILE.read_text(encoding="utf-8").strip()

    value = configured or secrets.token_urlsafe(48)
    _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(_SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _SECRET_FILE.read_text(encoding="utf-8").strip()
    with os.fdopen(fd, "w", encoding="utf-8") as secret_file:
        secret_file.write(value)
    return value


class Settings(BaseSettings):
    # Kept only to migrate existing deployments; new installs need no setting.
    SECRET_KEY: str = ""
    JWT_ALGORITHM: ClassVar[str] = "HS256"
    JWT_EXPIRE_MINUTES: ClassVar[int] = 1440

    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "five"
    MYSQL_PASSWORD: str = "five_password"
    MYSQL_DATABASE: str = "five_api"

    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    INIT_ADMIN_USERNAME: str = "admin"
    INIT_ADMIN_PASSWORD: str = "admin123"

    CHANNEL_HEALTH_THRESHOLD: int = 3
    CHANNEL_HEALTH_CHECK_INTERVAL: int = 60
    LOG_RETENTION_DAYS: int = 90

    STICKY_SESSION_ENABLED: bool = True
    STICKY_SESSION_TTL: int = 900

    @property
    def database_url(self) -> str:
        return (
            f"mysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
        )

    model_config = {
        "env_file": ("../.env", ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
settings.SECRET_KEY = _persistent_secret(settings.SECRET_KEY)

TORTOISE_ORM = {
    "connections": {
        "default": settings.database_url,
    },
    "apps": {
        "models": {
            "models": ["app.models", "aerich.models"],
            "default_connection": "default",
        },
    },
}
