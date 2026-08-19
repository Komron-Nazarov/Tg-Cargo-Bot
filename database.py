import asyncpg

from config import Settings


async def create_pool(settings: Settings) -> asyncpg.Pool:
    """Create the application pool without building a DSN containing secrets."""
    ssl = False if settings.db_ssl == "disable" else settings.db_ssl
    return await asyncpg.create_pool(
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
        ssl=ssl,
        min_size=1,
        max_size=5,
    )
