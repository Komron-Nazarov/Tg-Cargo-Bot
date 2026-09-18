from typing import Optional

import asyncpg

STATUS_NEW = "new"
STATUS_IN_PROGRESS = "in_progress"
STATUS_DONE = "done"

STATUS_LABELS = {
    STATUS_NEW: "🆕 Новая",
    STATUS_IN_PROGRESS: "🔄 В работе",
    STATUS_DONE: "✅ Готово",
}


async def add_order(
    pool: asyncpg.Pool,
    user_id: int,
    username: Optional[str],
    name: str,
    weight: float,
    country: str,
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO orders (user_id, username, name, weight, country)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            user_id,
            username,
            name,
            weight,
            country,
        )


async def get_user_orders(pool: asyncpg.Pool, user_id: int):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT id, name, weight, country, status, created_at
            FROM orders
            WHERE user_id = $1
            ORDER BY id DESC
            """,
            user_id,
        )


async def get_recent_user_orders(pool: asyncpg.Pool, user_id: int, limit: int = 5):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT id, name, weight, country, status, created_at
            FROM orders
            WHERE user_id = $1
            ORDER BY id DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )


async def get_order_for_admin(pool: asyncpg.Pool, order_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT o.id, o.user_id, o.username, o.name, o.weight, o.country,
                   o.status, o.created_at,
                   c.client_code, c.full_name, c.phone, c.delivery_city
            FROM orders o
            LEFT JOIN clients c ON c.telegram_user_id = o.user_id
            WHERE o.id = $1
            """,
            order_id,
        )


async def get_orders_by_status(
    pool: asyncpg.Pool,
    status: Optional[str] = None,
    limit: int = 10,
):
    async with pool.acquire() as conn:
        if status:
            return await conn.fetch(
                """
                SELECT o.id, o.user_id, o.username, o.name, o.weight, o.country,
                       o.status, c.client_code, c.full_name, c.phone, c.delivery_city
                FROM orders o
                LEFT JOIN clients c ON c.telegram_user_id = o.user_id
                WHERE o.status = $1
                ORDER BY o.id DESC
                LIMIT $2
                """,
                status,
                limit,
            )
        return await conn.fetch(
            """
            SELECT o.id, o.user_id, o.username, o.name, o.weight, o.country,
                   o.status, c.client_code, c.full_name, c.phone, c.delivery_city
            FROM orders o
            LEFT JOIN clients c ON c.telegram_user_id = o.user_id
            ORDER BY o.id DESC
            LIMIT $1
            """,
            limit,
        )


async def update_order_status(
    pool: asyncpg.Pool,
    order_id: int,
    status: str,
) -> Optional[int]:
    """Return the owner Telegram ID so the handler can notify them."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE orders SET status = $1 WHERE id = $2 RETURNING user_id",
            status,
            order_id,
        )
    return row["user_id"] if row else None
