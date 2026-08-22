import asyncpg

from services.delivery_service import next_delivery_status


DELIVERY_SELECT = """
    d.id, d.delivery_code, d.shipment_id, sh.shipment_code, d.client_id,
    c.client_code, c.telegram_user_id, c.full_name, c.phone AS client_phone,
    c.delivery_city, d.pickup_point_id, pp.pickup_code, pp.city AS pickup_city,
    pp.name AS pickup_name, pp.address AS pickup_address, pp.phone AS pickup_phone,
    d.status, d.assigned_by_telegram_id, d.assigned_at, d.ready_at,
    d.created_at, d.updated_at,
    ARRAY(SELECT cg.cargo_code FROM shipment_items si JOIN cargos cg ON cg.id=si.cargo_id
          WHERE si.shipment_id=d.shipment_id AND cg.client_id=d.client_id ORDER BY si.position) AS cargo_codes,
    ARRAY(SELECT cs.consolidation_code FROM shipment_items si JOIN consolidations cs ON cs.id=si.consolidation_id
          WHERE si.shipment_id=d.shipment_id AND cs.client_id=d.client_id ORDER BY si.position) AS consolidation_codes,
    ARRAY(SELECT tracking FROM (
        SELECT si.position, t.tracking_number AS tracking FROM shipment_items si
        JOIN cargos cg ON cg.id=si.cargo_id JOIN china_trackings t ON t.id=cg.china_tracking_id
        WHERE si.shipment_id=d.shipment_id AND cg.client_id=d.client_id
        UNION ALL
        SELECT si.position, t.tracking_number FROM shipment_items si
        JOIN consolidations cs ON cs.id=si.consolidation_id
        JOIN consolidation_items ci ON ci.consolidation_id=cs.id
        JOIN cargos cg ON cg.id=ci.cargo_id JOIN china_trackings t ON t.id=cg.china_tracking_id
        WHERE si.shipment_id=d.shipment_id AND cs.client_id=d.client_id
    ) q ORDER BY position) AS tracking_numbers
"""


class ShipmentNotFoundError(Exception): pass
class ShipmentNotClearedError(Exception): pass
class ClientNotFoundError(Exception): pass
class ClientNotInShipmentError(Exception): pass
class PickupUnavailableError(Exception): pass
class DeliveryAlreadyExistsError(Exception):
    def __init__(self, code): self.code = code
class DeliveryNotFoundError(Exception): pass
class DeliveryStatusChangedError(Exception): pass


async def get_assignment_candidate(pool, shipment_code, client_code, pickup_code):
    async with pool.acquire() as conn:
        return await _get_assignment_candidate(conn, shipment_code, client_code, pickup_code)


async def _get_assignment_candidate(conn, shipment_code, client_code, pickup_code):
    sh = await conn.fetchrow("SELECT id,shipment_code,status FROM shipments WHERE shipment_code=$1", shipment_code)
    if sh is None: raise ShipmentNotFoundError()
    if sh["status"] != "customs_cleared": raise ShipmentNotClearedError()
    client = await conn.fetchrow(
        "SELECT id,client_code,telegram_user_id,full_name,phone,delivery_city FROM clients WHERE client_code=$1",
        client_code,
    )
    if client is None: raise ClientNotFoundError()
    pickup = await conn.fetchrow(
        "SELECT id,pickup_code,city,name,address,phone,is_active FROM pickup_points WHERE pickup_code=$1",
        pickup_code,
    )
    if pickup is None or not pickup["is_active"]: raise PickupUnavailableError()
    units = await conn.fetch(
        """SELECT 'cargo' AS item_type, cg.id AS item_id, cg.cargo_code AS public_code,
                  cg.actual_weight_kg AS weight_kg, cg.pieces_count,
                  ARRAY[t.tracking_number] AS tracking_numbers
           FROM shipment_items si JOIN cargos cg ON cg.id=si.cargo_id
           JOIN china_trackings t ON t.id=cg.china_tracking_id
           WHERE si.shipment_id=$1 AND cg.client_id=$2
           UNION ALL
           SELECT 'consolidation', cs.id, cs.consolidation_code, cs.final_weight_kg,
                  cs.final_pieces_count,
                  ARRAY(SELECT t.tracking_number FROM consolidation_items ci
                    JOIN cargos cg ON cg.id=ci.cargo_id JOIN china_trackings t ON t.id=cg.china_tracking_id
                    WHERE ci.consolidation_id=cs.id ORDER BY ci.position)
           FROM shipment_items si JOIN consolidations cs ON cs.id=si.consolidation_id
           WHERE si.shipment_id=$1 AND cs.client_id=$2""",
        sh["id"], client["id"],
    )
    if not units: raise ClientNotInShipmentError()
    existing = await conn.fetchrow(
        "SELECT delivery_code FROM shipment_deliveries WHERE shipment_id=$1 AND client_id=$2",
        sh["id"], client["id"],
    )
    if existing: raise DeliveryAlreadyExistsError(existing["delivery_code"])
    return {
        **dict(sh), **dict(client), "shipment_id": sh["id"], "client_id": client["id"],
        "client_phone": client["phone"],
        "pickup_point_id": pickup["id"], "pickup_code": pickup["pickup_code"],
        "pickup_city": pickup["city"], "pickup_name": pickup["name"],
        "pickup_address": pickup["address"], "pickup_phone": pickup["phone"],
        "cargo_codes": [x["public_code"] for x in units if x["item_type"] == "cargo"],
        "consolidation_codes": [x["public_code"] for x in units if x["item_type"] == "consolidation"],
        "tracking_numbers": [n for x in units for n in x["tracking_numbers"]],
        "weight_kg": sum(x["weight_kg"] for x in units),
        "pieces_count": sum(x["pieces_count"] for x in units),
    }


async def _update_client_units(conn, shipment_id, client_id, from_status, to_status):
    direct = await conn.fetchval(
        """SELECT count(*) FROM shipment_items si JOIN cargos cg ON cg.id=si.cargo_id
           WHERE si.shipment_id=$1 AND cg.client_id=$2""", shipment_id, client_id)
    result = await conn.execute(
        """UPDATE cargos SET status=$3,updated_at=now() WHERE id IN
           (SELECT cg.id FROM shipment_items si JOIN cargos cg ON cg.id=si.cargo_id
            WHERE si.shipment_id=$1 AND cg.client_id=$2) AND status=$4""",
        shipment_id, client_id, to_status, from_status)
    if result != f"UPDATE {direct}": raise DeliveryStatusChangedError()
    cons = await conn.fetchval(
        """SELECT count(*) FROM shipment_items si JOIN consolidations cs ON cs.id=si.consolidation_id
           WHERE si.shipment_id=$1 AND cs.client_id=$2""", shipment_id, client_id)
    result = await conn.execute(
        """UPDATE consolidations SET status=$3,updated_at=now() WHERE id IN
           (SELECT cs.id FROM shipment_items si JOIN consolidations cs ON cs.id=si.consolidation_id
            WHERE si.shipment_id=$1 AND cs.client_id=$2) AND status=$4""",
        shipment_id, client_id, to_status, from_status)
    if result != f"UPDATE {cons}": raise DeliveryStatusChangedError()
    children = await conn.fetchval(
        """SELECT count(*) FROM consolidation_items ci JOIN consolidations cs ON cs.id=ci.consolidation_id
           JOIN shipment_items si ON si.consolidation_id=cs.id
           WHERE si.shipment_id=$1 AND cs.client_id=$2""", shipment_id, client_id)
    result = await conn.execute(
        """UPDATE cargos SET status=$3,updated_at=now() WHERE id IN
           (SELECT ci.cargo_id FROM consolidation_items ci JOIN consolidations cs ON cs.id=ci.consolidation_id
            JOIN shipment_items si ON si.consolidation_id=cs.id
            WHERE si.shipment_id=$1 AND cs.client_id=$2) AND status=$4""",
        shipment_id, client_id, to_status, from_status)
    if result != f"UPDATE {children}": raise DeliveryStatusChangedError()


async def _get_delivery_by_id(conn, delivery_id):
    return await conn.fetchrow(
        f"""SELECT {DELIVERY_SELECT} FROM shipment_deliveries d JOIN shipments sh ON sh.id=d.shipment_id
            JOIN clients c ON c.id=d.client_id JOIN pickup_points pp ON pp.id=d.pickup_point_id
            WHERE d.id=$1""", delivery_id)


async def create_delivery(pool, *, shipment_code, client_code, pickup_code, actor_id):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.fetchrow("SELECT id FROM shipments WHERE shipment_code=$1 FOR UPDATE", shipment_code)
            candidate = await _get_assignment_candidate(conn, shipment_code, client_code, pickup_code)
            row = await conn.fetchrow(
                """INSERT INTO shipment_deliveries
                   (shipment_id,client_id,pickup_point_id,assigned_by_telegram_id)
                   VALUES ($1,$2,$3,$4) RETURNING id,delivery_code""",
                candidate["shipment_id"], candidate["client_id"], candidate["pickup_point_id"], actor_id)
            await _update_client_units(conn, candidate["shipment_id"], candidate["client_id"],
                                       "customs_cleared", "assigned_pickup")
            return await _get_delivery_by_id(conn, row["id"])


async def get_delivery_by_code(pool, code):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"""SELECT {DELIVERY_SELECT} FROM shipment_deliveries d JOIN shipments sh ON sh.id=d.shipment_id
                JOIN clients c ON c.id=d.client_id JOIN pickup_points pp ON pp.id=d.pickup_point_id
                WHERE d.delivery_code=$1""", code)


async def list_deliveries(pool, limit=20, telegram_user_id=None):
    async with pool.acquire() as conn:
        return await conn.fetch(
            f"""SELECT {DELIVERY_SELECT} FROM shipment_deliveries d JOIN shipments sh ON sh.id=d.shipment_id
                JOIN clients c ON c.id=d.client_id JOIN pickup_points pp ON pp.id=d.pickup_point_id
                WHERE ($2::bigint IS NULL OR c.telegram_user_id=$2)
                ORDER BY d.updated_at DESC,d.id DESC LIMIT $1""", limit, telegram_user_id)


async def list_delivery_events(pool, delivery_id):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT id,delivery_id,from_status,to_status,note,created_by_telegram_id,occurred_at,created_at
               FROM delivery_events WHERE delivery_id=$1 ORDER BY occurred_at,id""", delivery_id)


async def advance_delivery(pool, *, delivery_code, expected_from_status, note, actor_id):
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT id,shipment_id,client_id,status FROM shipment_deliveries WHERE delivery_code=$1 FOR UPDATE",
                delivery_code)
            if row is None: raise DeliveryNotFoundError()
            to_status = next_delivery_status(expected_from_status)
            if row["status"] != expected_from_status:
                if row["status"] == to_status:
                    event = await conn.fetchrow(
                        "SELECT * FROM delivery_events WHERE delivery_id=$1 AND to_status=$2",
                        row["id"], to_status)
                    if event: return {"delivery": await _get_delivery_by_id(conn,row["id"]), "event":event,"created":False}
                raise DeliveryStatusChangedError()
            event = await conn.fetchrow(
                """INSERT INTO delivery_events(delivery_id,from_status,to_status,note,created_by_telegram_id)
                   VALUES($1,$2,$3,$4,$5) RETURNING *""",
                row["id"],expected_from_status,to_status,note,actor_id)
            result = await conn.execute(
                """UPDATE shipment_deliveries SET status=$2,
                   ready_at=CASE WHEN $2='ready_for_pickup' THEN now() ELSE NULL END,updated_at=now()
                   WHERE id=$1 AND status=$3""", row["id"],to_status,expected_from_status)
            if result != "UPDATE 1": raise DeliveryStatusChangedError()
            await _update_client_units(conn,row["shipment_id"],row["client_id"],expected_from_status,to_status)
            return {"delivery":await _get_delivery_by_id(conn,row["id"]),"event":event,"created":True}
