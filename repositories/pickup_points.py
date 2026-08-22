import asyncpg


PICKUP_FIELDS = """
    id, pickup_code, city, name, address, phone, note, is_active,
    created_by_telegram_id, created_at, updated_at
"""


async def create_pickup_point(pool: asyncpg.Pool, *, city: str, name: str,
                              address: str, phone: str | None, note: str | None,
                              created_by_telegram_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"""INSERT INTO pickup_points
                (city, name, address, phone, note, created_by_telegram_id)
                VALUES ($1,$2,$3,$4,$5,$6) RETURNING {PICKUP_FIELDS}""",
            city, name, address, phone, note, created_by_telegram_id,
        )


async def list_active_pickup_points(pool: asyncpg.Pool, limit=50):
    async with pool.acquire() as conn:
        return await conn.fetch(
            f"SELECT {PICKUP_FIELDS} FROM pickup_points WHERE is_active=true ORDER BY city,id LIMIT $1",
            limit,
        )


async def get_pickup_point_by_code(pool: asyncpg.Pool, code: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"SELECT {PICKUP_FIELDS} FROM pickup_points WHERE pickup_code=$1", code
        )
