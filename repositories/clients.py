from typing import Optional

import asyncpg


CLIENT_FIELDS = """
    id, client_code, telegram_user_id, telegram_username,
    full_name, phone, delivery_city, is_active, created_at, updated_at
"""


async def get_client_by_telegram_id(
    pool: asyncpg.Pool,
    telegram_user_id: int,
):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"SELECT {CLIENT_FIELDS} FROM clients WHERE telegram_user_id = $1",
            telegram_user_id,
        )


async def get_client_by_code(pool: asyncpg.Pool, client_code: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"SELECT {CLIENT_FIELDS} FROM clients WHERE client_code = $1",
            client_code,
        )


async def list_recent_clients(pool: asyncpg.Pool, limit: int = 20, offset: int = 0):
    async with pool.acquire() as conn:
        return await conn.fetch(
            f"SELECT {CLIENT_FIELDS} FROM clients ORDER BY id DESC LIMIT $1 OFFSET $2",
            limit,
            offset,
        )


async def search_clients(pool: asyncpg.Pool, query: str, limit: int = 20):
    """Search by public ID, name or phone; keep the query parameterized."""
    escaped = query.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    async with pool.acquire() as conn:
        return await conn.fetch(
            f"""
            SELECT {CLIENT_FIELDS}
            FROM clients
            WHERE client_code ILIKE $1 ESCAPE '!'
               OR full_name ILIKE $1 ESCAPE '!'
               OR phone ILIKE $1 ESCAPE '!'
            ORDER BY id DESC
            LIMIT $2
            """,
            f"%{escaped}%",
            limit,
        )


async def create_client(
    pool: asyncpg.Pool,
    telegram_user_id: int,
    telegram_username: Optional[str],
    full_name: str,
    phone: str,
    delivery_city: str,
):
    """Create one client per Telegram account and return the persisted row.

    PostgreSQL's identity sequence generates the internal ID. The generated
    client_code column derives the public code from it, so concurrent inserts
    cannot receive the same Client ID.
    """
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"""
            INSERT INTO clients (
                telegram_user_id, telegram_username, full_name, phone, delivery_city
            )
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (telegram_user_id) DO UPDATE
            SET telegram_username = EXCLUDED.telegram_username
            RETURNING {CLIENT_FIELDS}
            """,
            telegram_user_id,
            telegram_username,
            full_name,
            phone,
            delivery_city,
        )
