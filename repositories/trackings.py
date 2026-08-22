import asyncpg


STATUS_DECLARED = "declared"
STATUS_CANCELLED = "cancelled"
STATUS_RECEIVED = "received"

TRACKING_FIELDS = """
    id, client_id, tracking_number, tracking_number_normalized,
    status, created_at, updated_at, cancelled_at
"""

ADMIN_TRACKING_FIELDS = """
    t.id, t.client_id, t.tracking_number, t.tracking_number_normalized,
    t.status, t.created_at, t.updated_at, t.cancelled_at,
    c.client_code, c.full_name, c.telegram_user_id, c.telegram_username
"""


async def create_tracking(
    pool: asyncpg.Pool,
    client_id: int,
    tracking_number: str,
    tracking_number_normalized: str,
):
    """Insert once; return None when the database unique constraint wins."""
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"""
            INSERT INTO china_trackings (
                client_id, tracking_number, tracking_number_normalized
            )
            VALUES ($1, $2, $3)
            ON CONFLICT (tracking_number_normalized) DO NOTHING
            RETURNING {TRACKING_FIELDS}
            """,
            client_id,
            tracking_number,
            tracking_number_normalized,
        )


async def get_tracking_by_normalized(pool: asyncpg.Pool, normalized: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"""
            SELECT {TRACKING_FIELDS}
            FROM china_trackings
            WHERE tracking_number_normalized = $1
            """,
            normalized,
        )


async def get_client_tracking(
    pool: asyncpg.Pool,
    tracking_id: int,
    client_id: int,
):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"""
            SELECT {TRACKING_FIELDS}
            FROM china_trackings
            WHERE id = $1 AND client_id = $2
            """,
            tracking_id,
            client_id,
        )


async def list_client_trackings(
    pool: asyncpg.Pool,
    client_id: int,
    limit: int = 20,
):
    async with pool.acquire() as conn:
        return await conn.fetch(
            f"""
            SELECT {TRACKING_FIELDS}
            FROM china_trackings
            WHERE client_id = $1
            ORDER BY created_at DESC, id DESC
            LIMIT $2
            """,
            client_id,
            limit,
        )


async def cancel_client_tracking(
    pool: asyncpg.Pool,
    tracking_id: int,
    client_id: int,
):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"""
            UPDATE china_trackings
            SET status = '{STATUS_CANCELLED}',
                cancelled_at = now(),
                updated_at = now()
            WHERE id = $1
              AND client_id = $2
              AND status = '{STATUS_DECLARED}'
            RETURNING {TRACKING_FIELDS}
            """,
            tracking_id,
            client_id,
        )


async def list_declared_trackings(pool: asyncpg.Pool, limit: int = 20):
    async with pool.acquire() as conn:
        return await conn.fetch(
            f"""
            SELECT {ADMIN_TRACKING_FIELDS}
            FROM china_trackings t
            JOIN clients c ON c.id = t.client_id
            WHERE t.status = $1
            ORDER BY t.created_at DESC, t.id DESC
            LIMIT $2
            """,
            STATUS_DECLARED,
            limit,
        )


async def search_trackings_by_client_code(
    pool: asyncpg.Pool,
    client_code: str,
    limit: int = 20,
):
    async with pool.acquire() as conn:
        return await conn.fetch(
            f"""
            SELECT {ADMIN_TRACKING_FIELDS}
            FROM china_trackings t
            JOIN clients c ON c.id = t.client_id
            WHERE c.client_code = $1
            ORDER BY t.created_at DESC, t.id DESC
            LIMIT $2
            """,
            client_code,
            limit,
        )


async def search_tracking_by_number(pool: asyncpg.Pool, normalized: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"""
            SELECT {ADMIN_TRACKING_FIELDS}
            FROM china_trackings t
            JOIN clients c ON c.id = t.client_id
            WHERE t.tracking_number_normalized = $1
            """,
            normalized,
        )
