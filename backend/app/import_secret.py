"""Import data/.secret_key from 0.3.0 and earlier into the database.

docker compose run --rm -e SECRET_KEY="$(cat data/.secret_key)" gateway python -m app.import_secret
"""

import asyncio

from tortoise import Tortoise

from app.config import TORTOISE_ORM, settings
from app.utils.secrets import load_secret_key


async def main() -> None:
    if not settings.SECRET_KEY:
        raise SystemExit("SECRET_KEY is empty")
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        await load_secret_key()
    finally:
        await Tortoise.close_connections()
    print("Secret stored in the database")


if __name__ == "__main__":
    asyncio.run(main())
