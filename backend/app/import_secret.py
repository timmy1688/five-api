"""Legacy entry point; credentials now migrate to external secrets, never into the database."""
import asyncio
from app.migrate_secrets import main

if __name__ == "__main__":
    asyncio.run(main())
