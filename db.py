# import psycopg2
# import os
# from dotenv import load_dotenv

# load_dotenv()

# conn = psycopg2.connect(
#     dbname=os.getenv("DB_NAME"),
#     user=os.getenv("DB_USER"),
#     password=os.getenv("DB_PASSWORD"),
#     host=os.getenv("DB_HOST"),
#     port=os.getenv("DB_PORT")
# )

# cursor = conn.cursor()

# cursor.execute("""
# CREATE TABLE IF NOT EXISTS orders (
#     id SERIAL PRIMARY KEY,
#     user_id BIGINT,
#     name TEXT,
#     weight REAL,
#     country TEXT,
#     status TEXT DEFAULT 'new'
# )
# """)

# conn.commit()


# def add_order(user_id, name, weight, country):
#     cursor.execute(
#         """
#         INSERT INTO orders (user_id, name, weight, country)
#         VALUES (%s, %s, %s, %s)
#         """,
#         (user_id, name, weight, country)
#     )
#     conn.commit()


# def get_orders():
#     cursor.execute("SELECT * FROM orders ORDER BY id DESC")
#     return cursor.fetchall()





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

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    username TEXT,
    name TEXT NOT NULL,
    weight REAL NOT NULL,
    country TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


async def create_pool(dsn: str, ssl_mode: str = "require") -> asyncpg.Pool:
    """Создаёт пул соединений и гарантирует наличие таблицы.
    Пул создаётся один раз при старте бота, а не на каждый запрос.

    ssl_mode="disable" — для локального Postgres без SSL.
    ssl_mode="require" — для Supabase и других managed-провайдеров,
    где сервер обрывает соединение без SSL (без проверки сертификата,
    для полной проверки цепочки нужен verify-full с CA-сертификатом
    из дашборда Supabase).
    """
    ssl = False if ssl_mode == "disable" else ssl_mode
    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5, ssl=ssl)
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLE_SQL)
    return pool


async def add_order(
    pool: asyncpg.Pool,
    user_id: int,
    username: Optional[str],
    name: str,
    weight: float,
    country: str,
) -> int:
    async with pool.acquire() as conn:
        order_id = await conn.fetchval(
            """
            INSERT INTO orders (user_id, username, name, weight, country)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            user_id, username, name, weight, country,
        )
    return order_id


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


async def get_orders_by_status(pool: asyncpg.Pool, status: Optional[str] = None, limit: int = 10):
    async with pool.acquire() as conn:
        if status:
            return await conn.fetch(
                """
                SELECT id, user_id, username, name, weight, country, status
                FROM orders
                WHERE status = $1
                ORDER BY id DESC
                LIMIT $2
                """,
                status, limit,
            )
        return await conn.fetch(
            """
            SELECT id, user_id, username, name, weight, country, status
            FROM orders
            ORDER BY id DESC
            LIMIT $1
            """,
            limit,
        )


async def update_order_status(pool: asyncpg.Pool, order_id: int, status: str) -> Optional[int]:
    """Возвращает user_id владельца заявки, чтобы уведомить его об изменении статуса."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE orders SET status = $1 WHERE id = $2 RETURNING user_id",
            status, order_id,
        )
    return row["user_id"] if row else None