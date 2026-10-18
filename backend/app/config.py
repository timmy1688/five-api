from typing import ClassVar

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Only seeds the secret stored in the database (load_secret_key); normally unset.
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

    METRICS_TOKEN: str = ""

    @field_validator("SECRET_KEY")
    @classmethod
    def _long_secret(cls, value: str) -> str:
        value = value.strip()
        if value and len(value) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return value

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
