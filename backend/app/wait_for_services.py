"""Block until MySQL and Redis accept connections, then exit.

The container runs this before `aerich upgrade`. A fresh MySQL volume takes
several seconds to initialise, and migrating before then fails the start.
"""

import asyncio
import sys
import time

import asyncmy
import redis.asyncio as redis

from app.config import settings

TIMEOUT_SECONDS = 120


async def _mysql_ready() -> bool:
    try:
        conn = await asyncmy.connect(
            host=settings.MYSQL_HOST,
            port=settings.MYSQL_PORT,
            user=settings.MYSQL_USER,
            password=settings.MYSQL_PASSWORD,
            db=settings.MYSQL_DATABASE,
            connect_timeout=3,
        )
    except Exception:
        return False
    conn.close()
    return True


async def _redis_ready() -> bool:
    client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=3)
    try:
        return bool(await client.ping())
    except Exception:
        return False
    finally:
        await client.aclose()


async def main() -> int:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while True:
        mysql_ok, redis_ok = await asyncio.gather(_mysql_ready(), _redis_ready())
        if mysql_ok and redis_ok:
            return 0
        if time.monotonic() >= deadline:
            print(f"services not ready: mysql={mysql_ok} redis={redis_ok}", file=sys.stderr)
            return 1
        print(f"waiting for services: mysql={mysql_ok} redis={redis_ok}", flush=True)
        await asyncio.sleep(2)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
