from typing import Mapping, Sequence

import asyncpg

from services.shipment_status_service import (
    next_shipment_status,
)


CARGO_READY = "received_china"
CONSOLIDATION_READY = "consolidated_china"

CARGO_CANDIDATE_SELECT = """
    'cargo' AS item_type, cg.id AS item_id, cg.cargo_code AS public_code,
    cg.client_id, cg.actual_weight_kg AS weight_kg,
    cg.volume_m3, cg.pieces_count, cg.status,
    c.client_code, c.telegram_user_id, c.full_name,
    ARRAY[t.tracking_number] AS tracking_numbers,
    ci.consolidation_id AS parent_consolidation_id,
    pcs.consolidation_code AS parent_consolidation_code,
    si.shipment_id, sh.shipment_code
"""

CONSOLIDATION_CANDIDATE_SELECT = """
    'consolidation' AS item_type, cs.id AS item_id,
    cs.consolidation_code AS public_code, cs.client_id,
    cs.final_weight_kg AS weight_kg, cs.final_volume_m3 AS volume_m3,
    cs.final_pieces_count AS pieces_count, cs.status,
    c.client_code, c.telegram_user_id, c.full_name,
    ARRAY(
        SELECT t.tracking_number
        FROM consolidation_items ci2
        JOIN cargos cg2 ON cg2.id = ci2.cargo_id
        JOIN china_trackings t ON t.id = cg2.china_tracking_id
        WHERE ci2.consolidation_id = cs.id ORDER BY ci2.position
    ) AS tracking_numbers,
    NULL::bigint AS parent_consolidation_id,
    NULL::text AS parent_consolidation_code,
    si.shipment_id, sh.shipment_code
"""

SHIPMENT_SELECT = """
    sh.id, sh.shipment_code, sh.transport_type, sh.transport_reference,
    sh.note, sh.origin_country, sh.destination_country, sh.status,
    sh.departed_at, sh.created_by_telegram_id, sh.created_at, sh.updated_at,
    (SELECT count(*) FROM shipment_items si WHERE si.shipment_id = sh.id) AS items_count,
    (SELECT count(DISTINCT client_id) FROM (
        SELECT cg.client_id FROM shipment_items si
        JOIN cargos cg ON cg.id = si.cargo_id WHERE si.shipment_id = sh.id
        UNION
        SELECT cs.client_id FROM shipment_items si
        JOIN consolidations cs ON cs.id = si.consolidation_id
        WHERE si.shipment_id = sh.id
    ) shipment_clients) AS clients_count
"""


class DispatchObjectNotFoundError(Exception):
    def __init__(self, code: str): self.code = code


class CargoInConsolidationError(Exception):
    def __init__(self, code: str, consolidation_code: str):
        self.code, self.consolidation_code = code, consolidation_code


class DispatchObjectAlreadyShippedError(Exception):
    def __init__(self, code: str, shipment_code: str | None):
        self.code, self.shipment_code = code, shipment_code


class DispatchObjectUnavailableError(Exception):
    def __init__(self, code: str): self.code = code


class ShipmentNotFoundError(Exception):
    def __init__(self, code: str):
        self.code = code


class ShipmentStatusChangedError(Exception):
    pass


def validate_dispatch_items(codes: Sequence[str], rows: Sequence[Mapping]):
    by_code = {row["public_code"]: row for row in rows}
    for code in codes:
        if code not in by_code:
            raise DispatchObjectNotFoundError(code)
    ordered = [by_code[code] for code in codes]
    for row in ordered:
        if row["shipment_id"] is not None:
            raise DispatchObjectAlreadyShippedError(row["public_code"], row["shipment_code"])
        if row["item_type"] == "cargo":
            if row["parent_consolidation_id"] is not None:
                raise CargoInConsolidationError(
                    row["public_code"], row["parent_consolidation_code"]
                )
            if row["status"] != CARGO_READY:
                raise DispatchObjectUnavailableError(row["public_code"])
        elif row["status"] != CONSOLIDATION_READY:
            raise DispatchObjectUnavailableError(row["public_code"])
    return ordered


async def _fetch_candidates(conn, cargo_codes, consolidation_codes, *, lock=False):
    rows = []
    if cargo_codes:
        rows.extend(await conn.fetch(
            f"""SELECT {CARGO_CANDIDATE_SELECT}
            FROM cargos cg JOIN china_trackings t ON t.id = cg.china_tracking_id
            JOIN clients c ON c.id = cg.client_id
            LEFT JOIN consolidation_items ci ON ci.cargo_id = cg.id
            LEFT JOIN consolidations pcs ON pcs.id = ci.consolidation_id
            LEFT JOIN shipment_items si ON si.cargo_id = cg.id
            LEFT JOIN shipments sh ON sh.id = si.shipment_id
            WHERE cg.cargo_code = ANY($1::text[])
            ORDER BY cg.id {"FOR UPDATE OF cg" if lock else ""}""",
            list(cargo_codes),
        ))
    if consolidation_codes:
        rows.extend(await conn.fetch(
            f"""SELECT {CONSOLIDATION_CANDIDATE_SELECT}
            FROM consolidations cs JOIN clients c ON c.id = cs.client_id
            LEFT JOIN shipment_items si ON si.consolidation_id = cs.id
            LEFT JOIN shipments sh ON sh.id = si.shipment_id
            WHERE cs.consolidation_code = ANY($1::text[])
            ORDER BY cs.id {"FOR UPDATE OF cs" if lock else ""}""",
            list(consolidation_codes),
        ))
    return rows


async def get_dispatch_candidates(pool: asyncpg.Pool, codes: Sequence[str]):
    cargo_codes = [code for code in codes if code.startswith("CG")]
    consolidation_codes = [code for code in codes if code.startswith("CS")]
    async with pool.acquire() as conn:
        rows = await _fetch_candidates(conn, cargo_codes, consolidation_codes)
    by_code = {row["public_code"]: row for row in rows}
    return [by_code[code] for code in codes if code in by_code]


async def _get_shipment_by_id(conn, shipment_id: int):
    return await conn.fetchrow(
        f"SELECT {SHIPMENT_SELECT} FROM shipments sh WHERE sh.id = $1", shipment_id
    )


async def create_shipment(
    pool: asyncpg.Pool, *, codes: Sequence[str], transport_type: str,
    transport_reference: str | None, note: str | None, created_by_telegram_id: int,
):
    if not 1 <= len(codes) <= 200 or len(set(codes)) != len(codes):
        raise ValueError("Shipment must contain 1 to 200 unique objects")
    cargo_codes = [code for code in codes if code.startswith("CG")]
    consolidation_codes = [code for code in codes if code.startswith("CS")]
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await _fetch_candidates(
                conn, cargo_codes, consolidation_codes, lock=True
            )
            by_code = {row["public_code"]: row for row in rows}
            for code in codes:
                if code not in by_code: raise DispatchObjectNotFoundError(code)
            ordered = [by_code[code] for code in codes]
            existing = {row["shipment_id"] for row in ordered}
            if len(existing) == 1 and None not in existing:
                return await _get_shipment_by_id(conn, existing.pop())
            ordered = validate_dispatch_items(codes, ordered)
            shipment = await conn.fetchrow(
                """INSERT INTO shipments (
                    transport_type, transport_reference, note, created_by_telegram_id
                ) VALUES ($1, $2, $3, $4) RETURNING id, shipment_code""",
                transport_type, transport_reference, note, created_by_telegram_id,
            )
            for position, row in enumerate(ordered, start=1):
                await conn.execute(
                    """INSERT INTO shipment_items (
                        shipment_id, cargo_id, consolidation_id, position
                    ) VALUES ($1, $2, $3, $4)""",
                    shipment["id"],
                    row["item_id"] if row["item_type"] == "cargo" else None,
                    row["item_id"] if row["item_type"] == "consolidation" else None,
                    position,
                )
            cargo_ids = [row["item_id"] for row in ordered if row["item_type"] == "cargo"]
            consolidation_ids = [
                row["item_id"] for row in ordered if row["item_type"] == "consolidation"
            ]
            if cargo_ids:
                result = await conn.execute(
                    """UPDATE cargos SET status='shipped_china', updated_at=now()
                    WHERE id=ANY($1::bigint[]) AND status='received_china'""", cargo_ids
                )
                if result != f"UPDATE {len(cargo_ids)}":
                    raise DispatchObjectUnavailableError(ordered[0]["public_code"])
            if consolidation_ids:
                child_count = await conn.fetchval(
                    "SELECT count(*) FROM consolidation_items WHERE consolidation_id=ANY($1::bigint[])",
                    consolidation_ids,
                )
                result = await conn.execute(
                    """UPDATE consolidations SET status='shipped_china', updated_at=now()
                    WHERE id=ANY($1::bigint[]) AND status='consolidated_china'""",
                    consolidation_ids,
                )
                if result != f"UPDATE {len(consolidation_ids)}":
                    raise DispatchObjectUnavailableError(ordered[0]["public_code"])
                result = await conn.execute(
                    """UPDATE cargos SET status='shipped_china', updated_at=now()
                    WHERE id IN (SELECT cargo_id FROM consolidation_items
                    WHERE consolidation_id=ANY($1::bigint[])) AND status='consolidated'""",
                    consolidation_ids,
                )
                if result != f"UPDATE {child_count}":
                    raise DispatchObjectUnavailableError(ordered[0]["public_code"])
            return await _get_shipment_by_id(conn, shipment["id"])


async def list_recent_shipments(pool: asyncpg.Pool, limit: int = 20):
    async with pool.acquire() as conn:
        return await conn.fetch(
            f"SELECT {SHIPMENT_SELECT} FROM shipments sh ORDER BY sh.departed_at DESC, sh.id DESC LIMIT $1",
            limit,
        )


async def get_shipment_by_code(pool: asyncpg.Pool, code: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"SELECT {SHIPMENT_SELECT} FROM shipments sh WHERE sh.shipment_code=$1", code
        )


async def get_shipment_for_object(pool: asyncpg.Pool, code: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"""SELECT {SHIPMENT_SELECT} FROM shipment_items si
            JOIN shipments sh ON sh.id=si.shipment_id
            LEFT JOIN cargos cg ON cg.id=si.cargo_id
            LEFT JOIN consolidations cs ON cs.id=si.consolidation_id
            WHERE cg.cargo_code=$1 OR cs.consolidation_code=$1""", code
        )


async def get_shipment_items(pool: asyncpg.Pool, shipment_id: int):
    async with pool.acquire() as conn:
        cargo_rows = await conn.fetch(
            f"""SELECT {CARGO_CANDIDATE_SELECT}, selected.position AS shipment_position
            FROM shipment_items selected
            JOIN cargos cg ON cg.id=selected.cargo_id
            JOIN china_trackings t ON t.id=cg.china_tracking_id
            JOIN clients c ON c.id=cg.client_id
            LEFT JOIN consolidation_items ci ON ci.cargo_id=cg.id
            LEFT JOIN consolidations pcs ON pcs.id=ci.consolidation_id
            JOIN shipment_items si ON si.id=selected.id JOIN shipments sh ON sh.id=si.shipment_id
            WHERE selected.shipment_id=$1 ORDER BY selected.position""", shipment_id
        )
        consolidation_rows = await conn.fetch(
            f"""SELECT {CONSOLIDATION_CANDIDATE_SELECT}, selected.position AS shipment_position
            FROM shipment_items selected
            JOIN consolidations cs ON cs.id=selected.consolidation_id
            JOIN clients c ON c.id=cs.client_id
            JOIN shipment_items si ON si.id=selected.id JOIN shipments sh ON sh.id=si.shipment_id
            WHERE selected.shipment_id=$1 ORDER BY selected.position""", shipment_id
        )
        return sorted(
            [*cargo_rows, *consolidation_rows],
            key=lambda row: row["shipment_position"],
        )


async def list_client_shipment_units(pool: asyncpg.Pool, telegram_user_id: int, limit=20):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """WITH client_shipments AS (
                SELECT DISTINCT sh.id FROM shipments sh JOIN shipment_items si ON si.shipment_id=sh.id
                LEFT JOIN cargos cg ON cg.id=si.cargo_id
                LEFT JOIN consolidations cs ON cs.id=si.consolidation_id
                JOIN clients c ON c.id=COALESCE(cg.client_id, cs.client_id)
                WHERE c.telegram_user_id=$1 ORDER BY sh.id DESC LIMIT $2
            )
            SELECT sh.id, sh.shipment_code, sh.transport_type, sh.transport_reference,
                   sh.status, sh.departed_at, sh.updated_at, 'cargo' AS item_type,
                   cg.cargo_code AS public_code, cg.client_id,
                   cg.actual_weight_kg AS weight_kg, cg.volume_m3, cg.pieces_count,
                   ARRAY[t.tracking_number] AS tracking_numbers, c.telegram_user_id
            FROM client_shipments wanted JOIN shipments sh ON sh.id=wanted.id
            JOIN shipment_items si ON si.shipment_id=sh.id JOIN cargos cg ON cg.id=si.cargo_id
            JOIN china_trackings t ON t.id=cg.china_tracking_id JOIN clients c ON c.id=cg.client_id
            WHERE c.telegram_user_id=$1
            UNION ALL
            SELECT sh.id, sh.shipment_code, sh.transport_type, sh.transport_reference,
                   sh.status, sh.departed_at, sh.updated_at, 'consolidation', cs.consolidation_code,
                   cs.client_id, cs.final_weight_kg, cs.final_volume_m3, cs.final_pieces_count,
                   ARRAY(SELECT t.tracking_number FROM consolidation_items ci2
                     JOIN cargos cg2 ON cg2.id=ci2.cargo_id
                     JOIN china_trackings t ON t.id=cg2.china_tracking_id
                     WHERE ci2.consolidation_id=cs.id ORDER BY ci2.position), c.telegram_user_id
            FROM client_shipments wanted JOIN shipments sh ON sh.id=wanted.id
            JOIN shipment_items si ON si.shipment_id=sh.id
            JOIN consolidations cs ON cs.id=si.consolidation_id JOIN clients c ON c.id=cs.client_id
            WHERE c.telegram_user_id=$1 ORDER BY id DESC""",
            telegram_user_id, limit,
        )


async def list_shipment_events(pool: asyncpg.Pool, shipment_id: int):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT id, shipment_id, from_status, to_status, note,
                      created_by_telegram_id, occurred_at, created_at
               FROM shipment_events WHERE shipment_id=$1
               ORDER BY occurred_at, id""",
            shipment_id,
        )


async def _get_event(conn, shipment_id: int, to_status: str):
    return await conn.fetchrow(
        """SELECT id, shipment_id, from_status, to_status, note,
                  created_by_telegram_id, occurred_at, created_at
           FROM shipment_events WHERE shipment_id=$1 AND to_status=$2""",
        shipment_id,
        to_status,
    )


async def advance_shipment_status(
    pool: asyncpg.Pool,
    *,
    shipment_code: str,
    expected_from_status: str,
    note: str | None,
    created_by_telegram_id: int,
):
    async with pool.acquire() as conn:
        async with conn.transaction():
            shipment = await conn.fetchrow(
                """SELECT id, shipment_code, status
                   FROM shipments WHERE shipment_code=$1 FOR UPDATE""",
                shipment_code,
            )
            if shipment is None:
                raise ShipmentNotFoundError(shipment_code)

            expected_to_status = next_shipment_status(expected_from_status)
            if shipment["status"] != expected_from_status:
                if shipment["status"] == expected_to_status:
                    event = await _get_event(conn, shipment["id"], expected_to_status)
                    if event is not None:
                        return {
                            "shipment": await _get_shipment_by_id(conn, shipment["id"]),
                            "event": event,
                            "created": False,
                        }
                raise ShipmentStatusChangedError()

            event = await conn.fetchrow(
                """INSERT INTO shipment_events (
                       shipment_id, from_status, to_status, note,
                       created_by_telegram_id
                   ) VALUES ($1, $2, $3, $4, $5)
                   RETURNING id, shipment_id, from_status, to_status, note,
                             created_by_telegram_id, occurred_at, created_at""",
                shipment["id"],
                expected_from_status,
                expected_to_status,
                note,
                created_by_telegram_id,
            )

            result = await conn.execute(
                """UPDATE shipments SET status=$2, updated_at=now()
                   WHERE id=$1 AND status=$3""",
                shipment["id"],
                expected_to_status,
                expected_from_status,
            )
            if result != "UPDATE 1":
                raise ShipmentStatusChangedError()

            object_from_status = (
                "shipped_china"
                if expected_from_status == "departed_china"
                else expected_from_status
            )
            standalone_count = await conn.fetchval(
                "SELECT count(*) FROM shipment_items WHERE shipment_id=$1 AND cargo_id IS NOT NULL",
                shipment["id"],
            )
            if standalone_count:
                result = await conn.execute(
                    """UPDATE cargos SET status=$2, updated_at=now()
                       WHERE id IN (
                           SELECT cargo_id FROM shipment_items
                           WHERE shipment_id=$1 AND cargo_id IS NOT NULL
                       ) AND status=$3""",
                    shipment["id"],
                    expected_to_status,
                    object_from_status,
                )
                if result != f"UPDATE {standalone_count}":
                    raise ShipmentStatusChangedError()

            consolidation_count = await conn.fetchval(
                """SELECT count(*) FROM shipment_items
                   WHERE shipment_id=$1 AND consolidation_id IS NOT NULL""",
                shipment["id"],
            )
            if consolidation_count:
                result = await conn.execute(
                    """UPDATE consolidations SET status=$2, updated_at=now()
                       WHERE id IN (
                           SELECT consolidation_id FROM shipment_items
                           WHERE shipment_id=$1 AND consolidation_id IS NOT NULL
                       ) AND status=$3""",
                    shipment["id"],
                    expected_to_status,
                    object_from_status,
                )
                if result != f"UPDATE {consolidation_count}":
                    raise ShipmentStatusChangedError()

                child_count = await conn.fetchval(
                    """SELECT count(*) FROM consolidation_items ci
                       WHERE ci.consolidation_id IN (
                           SELECT consolidation_id FROM shipment_items
                           WHERE shipment_id=$1 AND consolidation_id IS NOT NULL
                       )""",
                    shipment["id"],
                )
                result = await conn.execute(
                    """UPDATE cargos SET status=$2, updated_at=now()
                       WHERE id IN (
                           SELECT ci.cargo_id FROM consolidation_items ci
                           WHERE ci.consolidation_id IN (
                               SELECT consolidation_id FROM shipment_items
                               WHERE shipment_id=$1 AND consolidation_id IS NOT NULL
                           )
                       ) AND status=$3""",
                    shipment["id"],
                    expected_to_status,
                    object_from_status,
                )
                if result != f"UPDATE {child_count}":
                    raise ShipmentStatusChangedError()

            return {
                "shipment": await _get_shipment_by_id(conn, shipment["id"]),
                "event": event,
                "created": True,
            }
