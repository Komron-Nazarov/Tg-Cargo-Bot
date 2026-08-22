from decimal import Decimal
from typing import Mapping, Optional, Sequence

import asyncpg


STATUS_RECEIVED_CHINA = "received_china"
STATUS_CONSOLIDATED = "consolidated"

CANDIDATE_SELECT = """
    cg.id, cg.cargo_code, cg.client_id, cg.actual_weight_kg,
    cg.volume_m3, cg.pieces_count, cg.status,
    t.tracking_number,
    c.client_code, c.telegram_user_id, c.full_name, c.phone, c.delivery_city,
    ci.consolidation_id, cs.consolidation_code
"""

CONSOLIDATION_SELECT = """
    cs.id, cs.consolidation_code, cs.client_id, cs.description,
    cs.final_weight_kg, cs.final_volume_m3, cs.final_pieces_count,
    cs.status, cs.consolidated_at, cs.consolidated_by_telegram_id,
    cs.created_at, cs.updated_at,
    c.client_code, c.telegram_user_id, c.telegram_username,
    c.full_name, c.phone, c.delivery_city,
    ARRAY(
        SELECT cg.cargo_code
        FROM consolidation_items ci
        JOIN cargos cg ON cg.id = ci.cargo_id
        WHERE ci.consolidation_id = cs.id
        ORDER BY ci.position
    ) AS cargo_codes,
    ARRAY(
        SELECT t.tracking_number
        FROM consolidation_items ci
        JOIN cargos cg ON cg.id = ci.cargo_id
        JOIN china_trackings t ON t.id = cg.china_tracking_id
        WHERE ci.consolidation_id = cs.id
        ORDER BY ci.position
    ) AS tracking_numbers,
    (SELECT count(*) FROM consolidation_photos cp
     WHERE cp.consolidation_id = cs.id) AS photos_count
"""


class CargoNotFoundError(Exception):
    def __init__(self, cargo_code: str):
        self.cargo_code = cargo_code


class CargoDifferentClientsError(Exception):
    pass


class CargoAlreadyConsolidatedError(Exception):
    def __init__(self, cargo_code: str, consolidation_code: Optional[str]):
        self.cargo_code = cargo_code
        self.consolidation_code = consolidation_code


class CargoUnavailableError(Exception):
    def __init__(self, cargo_code: str):
        self.cargo_code = cargo_code


def validate_candidates(cargo_codes: Sequence[str], cargos: Sequence[Mapping]):
    rows_by_code = {row["cargo_code"]: row for row in cargos}
    for code in cargo_codes:
        if code not in rows_by_code:
            raise CargoNotFoundError(code)
    ordered = [rows_by_code[code] for code in cargo_codes]
    if len({row["client_id"] for row in ordered}) != 1:
        raise CargoDifferentClientsError
    for row in ordered:
        if row["consolidation_id"] is not None:
            raise CargoAlreadyConsolidatedError(
                row["cargo_code"], row["consolidation_code"]
            )
        if row["status"] != STATUS_RECEIVED_CHINA:
            raise CargoUnavailableError(row["cargo_code"])
    return ordered


async def get_cargos_for_consolidation(pool: asyncpg.Pool, cargo_codes: Sequence[str]):
    async with pool.acquire() as conn:
        return await conn.fetch(
            f"""
            SELECT {CANDIDATE_SELECT}
            FROM cargos cg
            JOIN china_trackings t ON t.id = cg.china_tracking_id
            JOIN clients c ON c.id = cg.client_id
            LEFT JOIN consolidation_items ci ON ci.cargo_id = cg.id
            LEFT JOIN consolidations cs ON cs.id = ci.consolidation_id
            WHERE cg.cargo_code = ANY($1::text[])
            ORDER BY array_position($1::text[], cg.cargo_code)
            """,
            list(cargo_codes),
        )


async def _get_consolidation_by_id(conn, consolidation_id: int):
    return await conn.fetchrow(
        f"""
        SELECT {CONSOLIDATION_SELECT}
        FROM consolidations cs
        JOIN clients c ON c.id = cs.client_id
        WHERE cs.id = $1
        """,
        consolidation_id,
    )


async def create_consolidation(
    pool: asyncpg.Pool,
    *,
    cargo_codes: Sequence[str],
    description: Optional[str],
    final_weight_kg: Decimal,
    final_volume_m3: Optional[Decimal],
    final_pieces_count: int,
    photos: Sequence[Mapping[str, str]],
    consolidated_by_telegram_id: int,
):
    if not 2 <= len(cargo_codes) <= 50 or len(set(cargo_codes)) != len(cargo_codes):
        raise ValueError("Consolidation must contain 2 to 50 unique cargos")
    if not 1 <= len(photos) <= 10:
        raise ValueError("Consolidation must contain 1 to 10 photos")
    if len({photo["file_unique_id"] for photo in photos}) != len(photos):
        raise ValueError("Consolidation photos must be unique")

    async with pool.acquire() as conn:
        async with conn.transaction():
            locked = await conn.fetch(
                f"""
                SELECT {CANDIDATE_SELECT}
                FROM cargos cg
                JOIN china_trackings t ON t.id = cg.china_tracking_id
                JOIN clients c ON c.id = cg.client_id
                LEFT JOIN consolidation_items ci ON ci.cargo_id = cg.id
                LEFT JOIN consolidations cs ON cs.id = ci.consolidation_id
                WHERE cg.cargo_code = ANY($1::text[])
                ORDER BY cg.id
                FOR UPDATE OF cg
                """,
                list(cargo_codes),
            )

            rows_by_code = {row["cargo_code"]: row for row in locked}
            for code in cargo_codes:
                if code not in rows_by_code:
                    raise CargoNotFoundError(code)
            requested = [rows_by_code[code] for code in cargo_codes]

            existing_ids = {row["consolidation_id"] for row in requested}
            if len(existing_ids) == 1 and None not in existing_ids:
                return await _get_consolidation_by_id(conn, existing_ids.pop())

            ordered = validate_candidates(cargo_codes, requested)
            consolidation = await conn.fetchrow(
                """
                INSERT INTO consolidations (
                    client_id, description, final_weight_kg,
                    final_volume_m3, final_pieces_count,
                    consolidated_by_telegram_id
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id, consolidation_code
                """,
                ordered[0]["client_id"],
                description,
                final_weight_kg,
                final_volume_m3,
                final_pieces_count,
                consolidated_by_telegram_id,
            )
            for position, cargo in enumerate(ordered, start=1):
                await conn.execute(
                    """
                    INSERT INTO consolidation_items (
                        consolidation_id, cargo_id, position
                    )
                    VALUES ($1, $2, $3)
                    """,
                    consolidation["id"],
                    cargo["id"],
                    position,
                )
            for position, photo in enumerate(photos, start=1):
                await conn.execute(
                    """
                    INSERT INTO consolidation_photos (
                        consolidation_id, telegram_file_id,
                        telegram_file_unique_id, position
                    )
                    VALUES ($1, $2, $3, $4)
                    """,
                    consolidation["id"],
                    photo["file_id"],
                    photo["file_unique_id"],
                    position,
                )
            cargo_ids = [row["id"] for row in ordered]
            updated = await conn.execute(
                """
                UPDATE cargos
                SET status = 'consolidated', updated_at = now()
                WHERE id = ANY($1::bigint[]) AND status = 'received_china'
                """,
                cargo_ids,
            )
            if updated != f"UPDATE {len(cargo_ids)}":
                raise CargoUnavailableError(ordered[0]["cargo_code"])
            return await _get_consolidation_by_id(conn, consolidation["id"])


async def list_client_consolidations(
    pool: asyncpg.Pool,
    client_id: int,
    limit: int = 20,
):
    async with pool.acquire() as conn:
        return await conn.fetch(
            f"""
            SELECT {CONSOLIDATION_SELECT}
            FROM consolidations cs
            JOIN clients c ON c.id = cs.client_id
            WHERE cs.client_id = $1
            ORDER BY cs.consolidated_at DESC, cs.id DESC
            LIMIT $2
            """,
            client_id,
            limit,
        )


async def list_recent_consolidations(pool: asyncpg.Pool, limit: int = 20):
    async with pool.acquire() as conn:
        return await conn.fetch(
            f"""
            SELECT {CONSOLIDATION_SELECT}
            FROM consolidations cs
            JOIN clients c ON c.id = cs.client_id
            ORDER BY cs.consolidated_at DESC, cs.id DESC
            LIMIT $1
            """,
            limit,
        )


async def get_consolidation_by_code(pool: asyncpg.Pool, consolidation_code: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"""
            SELECT {CONSOLIDATION_SELECT}
            FROM consolidations cs
            JOIN clients c ON c.id = cs.client_id
            WHERE cs.consolidation_code = $1
            """,
            consolidation_code,
        )


async def get_client_consolidation_by_code(
    pool: asyncpg.Pool,
    telegram_user_id: int,
    consolidation_code: str,
):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"""
            SELECT {CONSOLIDATION_SELECT}
            FROM consolidations cs
            JOIN clients c ON c.id = cs.client_id
            WHERE cs.consolidation_code = $1 AND c.telegram_user_id = $2
            """,
            consolidation_code,
            telegram_user_id,
        )


async def get_consolidation_photos(pool: asyncpg.Pool, consolidation_id: int):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT telegram_file_id, telegram_file_unique_id, position
            FROM consolidation_photos
            WHERE consolidation_id = $1
            ORDER BY position
            """,
            consolidation_id,
        )


async def get_consolidation_for_cargo(pool: asyncpg.Pool, cargo_code: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"""
            SELECT {CONSOLIDATION_SELECT}
            FROM consolidation_items ci
            JOIN cargos cg ON cg.id = ci.cargo_id
            JOIN consolidations cs ON cs.id = ci.consolidation_id
            JOIN clients c ON c.id = cs.client_id
            WHERE cg.cargo_code = $1
            """,
            cargo_code,
        )
