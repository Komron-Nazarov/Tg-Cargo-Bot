from decimal import Decimal
from typing import Mapping, Optional, Sequence

import asyncpg


STATUS_DECLARED = "declared"
STATUS_CANCELLED = "cancelled"
STATUS_RECEIVED = "received"

CARGO_SELECT = """
    cg.id, cg.cargo_code, cg.client_id, cg.china_tracking_id,
    cg.description, cg.actual_weight_kg, cg.volume_m3, cg.pieces_count,
    cg.status, cg.received_at, cg.received_by_telegram_id,
    cg.created_at, cg.updated_at,
    t.tracking_number, t.tracking_number_normalized,
    c.client_code, c.telegram_user_id, c.telegram_username,
    c.full_name, c.phone, c.delivery_city,
    (SELECT count(*) FROM cargo_photos cp WHERE cp.cargo_id = cg.id) AS photos_count
"""

RECEIPT_TRACKING_SELECT = """
    t.id, t.client_id, t.tracking_number, t.tracking_number_normalized,
    t.status, t.created_at, t.updated_at,
    c.client_code, c.telegram_user_id, c.telegram_username,
    c.full_name, c.phone, c.delivery_city,
    cg.id AS cargo_id, cg.cargo_code
"""


class TrackingNotFoundError(Exception):
    pass


class TrackingCancelledError(Exception):
    pass


class TrackingAlreadyReceivedError(Exception):
    pass


async def get_receipt_tracking_by_number(pool: asyncpg.Pool, normalized: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"""
            SELECT {RECEIPT_TRACKING_SELECT}
            FROM china_trackings t
            JOIN clients c ON c.id = t.client_id
            LEFT JOIN cargos cg ON cg.china_tracking_id = t.id
            WHERE t.tracking_number_normalized = $1
            """,
            normalized,
        )


async def get_receipt_tracking_by_id(pool: asyncpg.Pool, tracking_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"""
            SELECT {RECEIPT_TRACKING_SELECT}
            FROM china_trackings t
            JOIN clients c ON c.id = t.client_id
            LEFT JOIN cargos cg ON cg.china_tracking_id = t.id
            WHERE t.id = $1
            """,
            tracking_id,
        )


async def _get_cargo_by_id(conn, cargo_id: int):
    return await conn.fetchrow(
        f"""
        SELECT {CARGO_SELECT}
        FROM cargos cg
        JOIN china_trackings t ON t.id = cg.china_tracking_id
        JOIN clients c ON c.id = cg.client_id
        WHERE cg.id = $1
        """,
        cargo_id,
    )


async def create_cargo_from_tracking(
    pool: asyncpg.Pool,
    *,
    tracking_id: int,
    description: Optional[str],
    actual_weight_kg: Decimal,
    volume_m3: Optional[Decimal],
    pieces_count: int,
    photos: Sequence[Mapping[str, str]],
    received_by_telegram_id: int,
):
    if not 1 <= len(photos) <= 10:
        raise ValueError("Cargo must have from 1 to 10 photos")
    if len({photo["file_unique_id"] for photo in photos}) != len(photos):
        raise ValueError("Cargo photos must be unique")
    async with pool.acquire() as conn:
        async with conn.transaction():
            tracking = await conn.fetchrow(
                """
                SELECT t.id, t.client_id, t.status, cg.id AS cargo_id
                FROM china_trackings t
                LEFT JOIN cargos cg ON cg.china_tracking_id = t.id
                WHERE t.id = $1
                FOR UPDATE OF t
                """,
                tracking_id,
            )
            if tracking is None:
                raise TrackingNotFoundError
            if tracking["cargo_id"] is not None:
                return await _get_cargo_by_id(conn, tracking["cargo_id"])
            if tracking["status"] == STATUS_CANCELLED:
                raise TrackingCancelledError
            if tracking["status"] != STATUS_DECLARED:
                raise TrackingAlreadyReceivedError

            cargo = await conn.fetchrow(
                """
                INSERT INTO cargos (
                    client_id, china_tracking_id, description,
                    actual_weight_kg, volume_m3, pieces_count,
                    received_by_telegram_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id, cargo_code
                """,
                tracking["client_id"],
                tracking_id,
                description,
                actual_weight_kg,
                volume_m3,
                pieces_count,
                received_by_telegram_id,
            )
            for position, photo in enumerate(photos, start=1):
                await conn.execute(
                    """
                    INSERT INTO cargo_photos (
                        cargo_id, telegram_file_id,
                        telegram_file_unique_id, position
                    )
                    VALUES ($1, $2, $3, $4)
                    """,
                    cargo["id"],
                    photo["file_id"],
                    photo["file_unique_id"],
                    position,
                )
            updated = await conn.execute(
                """
                UPDATE china_trackings
                SET status = 'received', updated_at = now()
                WHERE id = $1 AND status = 'declared'
                """,
                tracking_id,
            )
            if updated != "UPDATE 1":
                raise TrackingAlreadyReceivedError
            return await _get_cargo_by_id(conn, cargo["id"])


async def list_client_cargos(pool: asyncpg.Pool, client_id: int, limit: int = 20):
    async with pool.acquire() as conn:
        return await conn.fetch(
            f"""
            SELECT {CARGO_SELECT}
            FROM cargos cg
            JOIN china_trackings t ON t.id = cg.china_tracking_id
            JOIN clients c ON c.id = cg.client_id
            WHERE cg.client_id = $1
            ORDER BY cg.received_at DESC, cg.id DESC
            LIMIT $2
            """,
            client_id,
            limit,
        )


async def list_recent_cargos(pool: asyncpg.Pool, limit: int = 20):
    async with pool.acquire() as conn:
        return await conn.fetch(
            f"""
            SELECT {CARGO_SELECT}
            FROM cargos cg
            JOIN china_trackings t ON t.id = cg.china_tracking_id
            JOIN clients c ON c.id = cg.client_id
            ORDER BY cg.received_at DESC, cg.id DESC
            LIMIT $1
            """,
            limit,
        )


async def get_cargo_by_code(pool: asyncpg.Pool, cargo_code: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"""
            SELECT {CARGO_SELECT}
            FROM cargos cg
            JOIN china_trackings t ON t.id = cg.china_tracking_id
            JOIN clients c ON c.id = cg.client_id
            WHERE cg.cargo_code = $1
            """,
            cargo_code,
        )


async def get_client_cargo_by_code(
    pool: asyncpg.Pool,
    telegram_user_id: int,
    cargo_code: str,
):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"""
            SELECT {CARGO_SELECT}
            FROM cargos cg
            JOIN china_trackings t ON t.id = cg.china_tracking_id
            JOIN clients c ON c.id = cg.client_id
            WHERE cg.cargo_code = $1 AND c.telegram_user_id = $2
            """,
            cargo_code,
            telegram_user_id,
        )


async def get_cargo_photos(pool: asyncpg.Pool, cargo_id: int):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT telegram_file_id, telegram_file_unique_id, position
            FROM cargo_photos
            WHERE cargo_id = $1
            ORDER BY position
            """,
            cargo_id,
        )
