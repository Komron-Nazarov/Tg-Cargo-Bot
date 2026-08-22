import asyncpg

from repositories.deliveries import _get_delivery_by_id, _update_client_units


class DeliveryNotFoundError(Exception): pass
class DeliveryNotReadyError(Exception): pass
class HandoverAlreadyExistsError(Exception): pass
class HandoverRequiredError(Exception): pass
class PaymentAlreadyExistsError(Exception):
    def __init__(self,code): self.code=code
class CompletionStatusError(Exception): pass


PAYMENT_SELECT="""
    p.id,p.payment_code,p.delivery_id,d.delivery_code,sh.shipment_code,
    d.client_id,c.client_code,c.telegram_user_id,c.full_name,c.phone AS client_phone,
    p.amount,p.currency,p.payment_method,p.reference,p.note,
    p.recorded_by_telegram_id,p.paid_at,p.created_at
"""


async def get_handover_candidate(pool,delivery_code):
    async with pool.acquire() as conn:
        d=await conn.fetchrow("SELECT id,status FROM shipment_deliveries WHERE delivery_code=$1",delivery_code)
        if d is None: raise DeliveryNotFoundError()
        existing=await conn.fetchrow("SELECT * FROM handover_records WHERE delivery_id=$1",d["id"])
        if existing: raise HandoverAlreadyExistsError()
        if d["status"]!="ready_for_pickup": raise DeliveryNotReadyError()
        return await _get_delivery_by_id(conn,d["id"])


async def create_handover(pool,*,delivery_code,recipient_type,recipient_name,recipient_phone,note,actor_id):
    async with pool.acquire() as conn:
        async with conn.transaction():
            d=await conn.fetchrow("SELECT id,shipment_id,client_id,status FROM shipment_deliveries WHERE delivery_code=$1 FOR UPDATE",delivery_code)
            if d is None: raise DeliveryNotFoundError()
            existing=await conn.fetchrow("SELECT * FROM handover_records WHERE delivery_id=$1",d["id"])
            if existing:
                return {"delivery":await _get_delivery_by_id(conn,d["id"]),"handover":existing,"created":False}
            if d["status"]!="ready_for_pickup": raise DeliveryNotReadyError()
            h=await conn.fetchrow("""INSERT INTO handover_records(delivery_id,recipient_type,recipient_name,recipient_phone,note,handed_over_by_telegram_id)
                VALUES($1,$2,$3,$4,$5,$6) RETURNING *""",d["id"],recipient_type,recipient_name,recipient_phone,note,actor_id)
            result=await conn.execute("UPDATE shipment_deliveries SET status='handed_over',updated_at=now() WHERE id=$1 AND status='ready_for_pickup'",d["id"])
            if result!="UPDATE 1": raise CompletionStatusError()
            await _update_client_units(conn,d["shipment_id"],d["client_id"],"ready_for_pickup","handed_over")
            return {"delivery":await _get_delivery_by_id(conn,d["id"]),"handover":h,"created":True}


async def get_payment_candidate(pool,delivery_code):
    async with pool.acquire() as conn:
        d=await conn.fetchrow("SELECT id,status FROM shipment_deliveries WHERE delivery_code=$1",delivery_code)
        if d is None: raise DeliveryNotFoundError()
        payment=await conn.fetchrow("SELECT payment_code FROM payment_records WHERE delivery_id=$1",d["id"])
        if payment: raise PaymentAlreadyExistsError(payment["payment_code"])
        handover=await conn.fetchrow("SELECT * FROM handover_records WHERE delivery_id=$1",d["id"])
        if handover is None or d["status"]!="handed_over": raise HandoverRequiredError()
        return {"delivery":await _get_delivery_by_id(conn,d["id"]),"handover":handover}


async def create_payment(pool,*,delivery_code,amount,payment_method,reference,note,actor_id):
    async with pool.acquire() as conn:
        async with conn.transaction():
            d=await conn.fetchrow("SELECT id,shipment_id,client_id,status FROM shipment_deliveries WHERE delivery_code=$1 FOR UPDATE",delivery_code)
            if d is None: raise DeliveryNotFoundError()
            existing=await conn.fetchrow("SELECT * FROM payment_records WHERE delivery_id=$1",d["id"])
            if existing:
                return {"delivery":await _get_delivery_by_id(conn,d["id"]),"payment":await _get_payment_by_id(conn,existing["id"]),"created":False}
            handover=await conn.fetchrow("SELECT id FROM handover_records WHERE delivery_id=$1",d["id"])
            if handover is None or d["status"]!="handed_over": raise HandoverRequiredError()
            p=await conn.fetchrow("""INSERT INTO payment_records(delivery_id,amount,payment_method,reference,note,recorded_by_telegram_id)
                VALUES($1,$2,$3,$4,$5,$6) RETURNING id,payment_code""",d["id"],amount,payment_method,reference,note,actor_id)
            result=await conn.execute("UPDATE shipment_deliveries SET status='completed',updated_at=now() WHERE id=$1 AND status='handed_over'",d["id"])
            if result!="UPDATE 1": raise CompletionStatusError()
            await _update_client_units(conn,d["shipment_id"],d["client_id"],"handed_over","completed")
            return {"delivery":await _get_delivery_by_id(conn,d["id"]),"payment":await _get_payment_by_id(conn,p["id"]),"created":True}


async def _get_payment_by_id(conn,payment_id):
    return await conn.fetchrow(f"""SELECT {PAYMENT_SELECT} FROM payment_records p JOIN shipment_deliveries d ON d.id=p.delivery_id
        JOIN shipments sh ON sh.id=d.shipment_id JOIN clients c ON c.id=d.client_id WHERE p.id=$1""",payment_id)


async def list_handovers(pool,limit=20):
    async with pool.acquire() as conn:
        return await conn.fetch("""SELECT h.*,d.delivery_code,c.client_code,c.full_name,pp.pickup_code,pp.name AS pickup_name
            FROM handover_records h JOIN shipment_deliveries d ON d.id=h.delivery_id JOIN clients c ON c.id=d.client_id
            JOIN pickup_points pp ON pp.id=d.pickup_point_id ORDER BY h.handed_over_at DESC,h.id DESC LIMIT $1""",limit)


async def list_payments(pool,limit=20):
    async with pool.acquire() as conn:
        return await conn.fetch(f"""SELECT {PAYMENT_SELECT} FROM payment_records p JOIN shipment_deliveries d ON d.id=p.delivery_id
            JOIN shipments sh ON sh.id=d.shipment_id JOIN clients c ON c.id=d.client_id ORDER BY p.paid_at DESC,p.id DESC LIMIT $1""",limit)


async def get_payment(pool,code):
    async with pool.acquire() as conn:
        condition="p.payment_code=$1" if code.startswith("PY") else "d.delivery_code=$1"
        return await conn.fetchrow(f"""SELECT {PAYMENT_SELECT} FROM payment_records p JOIN shipment_deliveries d ON d.id=p.delivery_id
            JOIN shipments sh ON sh.id=d.shipment_id JOIN clients c ON c.id=d.client_id WHERE {condition}""",code)
