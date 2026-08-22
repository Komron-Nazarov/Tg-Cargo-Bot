import inspect
import unittest
from copy import deepcopy
from decimal import Decimal


class FakeContext:
    def __init__(self, value): self.value = value
    async def __aenter__(self): return self.value
    async def __aexit__(self, exc_type, exc, tb): return False


class FakeTransaction:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self): self.snapshot = self.conn.snapshot(); return self
    async def __aexit__(self, exc_type, exc, tb):
        if exc_type: self.conn.restore(self.snapshot)
        return False


class FakeCompletionConnection:
    def __init__(self, status="ready_for_pickup", fail_on=None):
        self.delivery = {
            "id": 1, "delivery_code": "DL000001", "shipment_id": 10,
            "shipment_code": "SH000001", "client_id": 20, "client_code": "C000001",
            "telegram_user_id": 123, "full_name": "Test Client", "client_phone": "+992900001122",
            "delivery_city": "Душанбе", "pickup_point_id": 30, "pickup_code": "PP000001",
            "pickup_city": "dushanbe", "pickup_name": "Point", "pickup_address": "Address 1",
            "pickup_phone": None, "status": status, "assigned_by_telegram_id": 999,
            "assigned_at": None, "ready_at": None, "created_at": None, "updated_at": None,
            "cargo_codes": ["CG000001"], "consolidation_codes": ["CS000001"],
            "tracking_numbers": ["LP123456789CN"],
        }
        self.handover = None; self.payment = None; self.fail_on = fail_on
        self.direct_status = status; self.consolidation_status = status; self.child_status = status
        self.foreign_status = "ready_for_pickup"

    def snapshot(self):
        return deepcopy((self.delivery, self.handover, self.payment, self.direct_status, self.consolidation_status, self.child_status, self.foreign_status))

    def restore(self, snapshot):
        self.delivery, self.handover, self.payment, self.direct_status, self.consolidation_status, self.child_status, self.foreign_status = snapshot

    def transaction(self): return FakeTransaction(self)

    def _complete_delivery(self):
        row = dict(self.delivery)
        row.update({
            "handed_over_at": self.handover and self.handover["handed_over_at"],
            "payment_code": self.payment and self.payment["payment_code"],
            "payment_amount": self.payment and self.payment["amount"],
            "payment_method": self.payment and self.payment["payment_method"],
            "paid_at": self.payment and self.payment["paid_at"],
        })
        return row

    def _complete_payment(self):
        return self.payment and {
            **self.payment, "delivery_code": "DL000001", "shipment_code": "SH000001",
            "client_id": 20, "client_code": "C000001", "telegram_user_id": 123,
            "full_name": "Test Client", "client_phone": "+992900001122",
        }

    async def fetchrow(self, query, *args):
        q = " ".join(query.upper().split())
        if "FROM SHIPMENT_DELIVERIES D JOIN SHIPMENTS" in q: return self._complete_delivery()
        if q.startswith("SELECT ID,STATUS FROM SHIPMENT_DELIVERIES"): return {"id": 1, "status": self.delivery["status"]}
        if q.startswith("SELECT ID,SHIPMENT_ID,CLIENT_ID,STATUS FROM SHIPMENT_DELIVERIES"): return {k: self.delivery[k] for k in ("id", "shipment_id", "client_id", "status")}
        if "SELECT * FROM HANDOVER_RECORDS" in q: return self.handover
        if "SELECT ID FROM HANDOVER_RECORDS" in q: return self.handover and {"id": self.handover["id"]}
        if "SELECT PAYMENT_CODE FROM PAYMENT_RECORDS" in q: return self.payment and {"payment_code": self.payment["payment_code"]}
        if "SELECT * FROM PAYMENT_RECORDS" in q: return self.payment
        if q.startswith("INSERT INTO HANDOVER_RECORDS"):
            self.handover = {"id": 1, "delivery_id": 1, "recipient_type": args[1], "recipient_name": args[2],
                "recipient_phone": args[3], "note": args[4], "handed_over_by_telegram_id": args[5],
                "handed_over_at": None, "created_at": None}
            return self.handover
        if q.startswith("INSERT INTO PAYMENT_RECORDS"):
            self.payment = {"id": 1, "payment_code": "PY000001", "delivery_id": 1, "amount": args[1],
                "currency": "TJS", "payment_method": args[2], "reference": args[3], "note": args[4],
                "recorded_by_telegram_id": args[5], "paid_at": None, "created_at": None}
            return {"id": 1, "payment_code": "PY000001"}
        if "FROM PAYMENT_RECORDS P JOIN SHIPMENT_DELIVERIES" in q: return self._complete_payment()
        raise AssertionError(q)

    async def fetchval(self, query, *args): return 1

    async def fetch(self, query, *args):
        q = " ".join(query.upper().split())
        if "FROM HANDOVER_RECORDS H" in q:
            return [] if self.handover is None else [{**self.handover, "delivery_code": "DL000001",
                "client_code": "C000001", "full_name": "Test Client", "pickup_code": "PP000001", "pickup_name": "Point"}]
        if "FROM PAYMENT_RECORDS P" in q: return [] if self.payment is None else [self._complete_payment()]
        raise AssertionError(q)

    async def execute(self, query, *args):
        q = " ".join(query.upper().split())
        if self.fail_on and self.fail_on in q: raise RuntimeError("forced failure")
        if q.startswith("UPDATE SHIPMENT_DELIVERIES"):
            self.delivery["status"] = args[1] if len(args) > 1 else ("completed" if "SET STATUS='COMPLETED'" in q else "handed_over")
            return "UPDATE 1"
        if q.startswith("UPDATE CARGOS SET"):
            if "CONSOLIDATION_ITEMS" in q: self.child_status = args[2]
            else: self.direct_status = args[2]
            return "UPDATE 1"
        if q.startswith("UPDATE CONSOLIDATIONS SET"):
            self.consolidation_status = args[2]; return "UPDATE 1"
        raise AssertionError(q)


class FakeCompletionPool:
    def __init__(self, status="ready_for_pickup", fail_on=None): self.conn = FakeCompletionConnection(status, fail_on)
    def acquire(self): return FakeContext(self.conn)


class CompletionServiceTests(unittest.TestCase):
    def test_payment_code_and_amount(self):
        from services.completion_service import format_payment_code, normalize_payment_code, parse_amount

        self.assertEqual(format_payment_code(1), "PY000001")
        self.assertEqual(normalize_payment_code(" py000001 "), "PY000001")
        self.assertEqual(parse_amount("250,50"), Decimal("250.50"))
        for value in ("0", "-1", "abc", "1.999"):
            with self.assertRaises(ValueError): parse_amount(value)

    def test_handover_and_payment_validation(self):
        from services.completion_service import (
            validate_note, validate_payment_method, validate_recipient_name,
            validate_recipient_phone, validate_recipient_type,
            validate_reference,
        )

        self.assertEqual(validate_recipient_type("client"), "client")
        self.assertEqual(validate_recipient_name(" Test Client "), "Test Client")
        self.assertIsNone(validate_recipient_phone("/skip"))
        self.assertIsNone(validate_note("/skip")); self.assertEqual(validate_reference(" R-1 "), "R-1")
        with self.assertRaises(ValueError): validate_payment_method("card")

    def test_notifications_and_cards_do_not_leak_internal_note(self):
        from services.completion_service import format_handover_notification, format_payment_notification

        delivery = {"delivery_code": "DL000001", "shipment_code": "SH000001", "handed_over_at": None}
        payment = {"payment_code": "PY000001", "delivery_code": "DL000001", "shipment_code": "SH000001", "client_code": "C000001",
            "amount": Decimal("150"), "payment_method": "cash", "reference": None,
            "paid_at": None, "note": "internal", "recorded_by_telegram_id": 999, "full_name": "Client"}
        handover_text = format_handover_notification(delivery)
        payment_text = format_payment_notification(payment)
        self.assertIn("Выдан получателю", handover_text)
        self.assertIn("PY000001", payment_text); self.assertIn("150.00 TJS", payment_text)
        self.assertNotIn("internal", payment_text); self.assertNotIn("999", payment_text)

    def test_internal_fields_are_hidden_from_client_payment(self):
        from services.completion_service import format_payment

        row = {
            "payment_code": "PY000001", "delivery_code": "DL000001", "shipment_code": "SH000001",
            "client_code": "C000001", "amount": Decimal("250.00"),
            "payment_method": "cash", "reference": None, "paid_at": None,
            "full_name": "Client", "note": "private", "recorded_by_telegram_id": 999,
        }
        client = format_payment(row)
        admin = format_payment(row, admin=True)
        self.assertNotIn("private", client); self.assertNotIn("999", client)
        self.assertIn("private", admin); self.assertIn("999", admin)


class CompletionArchitectureTests(unittest.TestCase):
    def test_dispatcher_and_commands_include_completion(self):
        from bot_app import create_dispatcher, set_commands

        self.assertIn("include_router(completion.router)", inspect.getsource(create_dispatcher))
        commands = inspect.getsource(set_commands)
        for command in ("handover", "record_payment", "handovers", "payments", "payment"):
            self.assertIn(f'command="{command}"', commands)

    def test_transactions_lock_and_scope_updates(self):
        from repositories.completions import create_handover, create_payment

        for function in (create_handover, create_payment):
            source = inspect.getsource(function).upper()
            self.assertIn("TRANSACTION", source)
            self.assertIn("FOR UPDATE", source)
            self.assertIn("_UPDATE_CLIENT_UNITS", source)
            self.assertNotIn("MAX(", source)

    def test_migration_is_additive_and_has_constraints(self):
        from migrations.runner import MIGRATIONS_DIR

        path = MIGRATIONS_DIR / "009_create_handovers_payments.sql"
        sql = path.read_text(encoding="utf-8").lower()
        self.assertIn("create table handover_records", sql)
        self.assertIn("create table payment_records", sql)
        self.assertIn("unique(delivery_id)", sql)
        self.assertIn("amount numeric(14,2)", sql)
        self.assertIn("handed_over_at timestamptz not null default now()", sql)
        self.assertIn("paid_at timestamptz not null default now()", sql)
        self.assertNotIn("drop table", sql)
        self.assertNotIn("delete from", sql)


class CompletionRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_handover_transaction_updates_only_clients_units(self):
        from repositories.completions import create_handover

        pool = FakeCompletionPool()
        result = await create_handover(pool, delivery_code="DL000001", recipient_type="client",
            recipient_name="Test Client", recipient_phone=None, note=None, actor_id=999)
        self.assertTrue(result["created"])
        self.assertEqual(pool.conn.delivery["status"], "handed_over")
        self.assertEqual(pool.conn.direct_status, "handed_over")
        self.assertEqual(pool.conn.consolidation_status, "handed_over")
        self.assertEqual(pool.conn.child_status, "handed_over")
        self.assertEqual(pool.conn.foreign_status, "ready_for_pickup")

    async def test_repeated_handover_returns_existing(self):
        from repositories.completions import create_handover

        pool = FakeCompletionPool()
        kwargs = dict(delivery_code="DL000001", recipient_type="client", recipient_name="Test Client",
            recipient_phone=None, note=None, actor_id=999)
        await create_handover(pool, **kwargs)
        result = await create_handover(pool, **kwargs)
        self.assertFalse(result["created"]); self.assertEqual(result["handover"]["id"], 1)

    async def test_handover_rejected_before_ready(self):
        from repositories.completions import DeliveryNotReadyError, create_handover

        with self.assertRaises(DeliveryNotReadyError):
            await create_handover(FakeCompletionPool("arrived_pickup"), delivery_code="DL000001",
                recipient_type="client", recipient_name="Test", recipient_phone=None, note=None, actor_id=999)

    async def test_handover_rolls_back_everything(self):
        from repositories.completions import create_handover

        pool = FakeCompletionPool(fail_on="UPDATE CONSOLIDATIONS")
        with self.assertRaises(RuntimeError):
            await create_handover(pool, delivery_code="DL000001", recipient_type="client",
                recipient_name="Test", recipient_phone=None, note=None, actor_id=999)
        self.assertIsNone(pool.conn.handover); self.assertEqual(pool.conn.delivery["status"], "ready_for_pickup")
        self.assertEqual(pool.conn.direct_status, "ready_for_pickup")

    async def test_payment_requires_handover(self):
        from repositories.completions import HandoverRequiredError, create_payment

        with self.assertRaises(HandoverRequiredError):
            await create_payment(FakeCompletionPool("handed_over"), delivery_code="DL000001",
                amount=Decimal("10"), payment_method="cash", reference=None, note=None, actor_id=999)

    async def test_payment_transaction_completes_all_client_units(self):
        from repositories.completions import create_handover, create_payment

        pool = FakeCompletionPool()
        await create_handover(pool, delivery_code="DL000001", recipient_type="client",
            recipient_name="Test", recipient_phone=None, note=None, actor_id=999)
        result = await create_payment(pool, delivery_code="DL000001", amount=Decimal("150.50"),
            payment_method="cash", reference="R-1", note=None, actor_id=999)
        self.assertTrue(result["created"]); self.assertEqual(result["payment"]["payment_code"], "PY000001")
        self.assertEqual(pool.conn.delivery["status"], "completed")
        self.assertEqual((pool.conn.direct_status, pool.conn.consolidation_status, pool.conn.child_status), ("completed",) * 3)
        self.assertEqual(pool.conn.foreign_status, "ready_for_pickup")

    async def test_repeated_payment_returns_same_payment(self):
        from repositories.completions import create_handover, create_payment

        pool = FakeCompletionPool()
        await create_handover(pool, delivery_code="DL000001", recipient_type="client",
            recipient_name="Test", recipient_phone=None, note=None, actor_id=999)
        kwargs = dict(delivery_code="DL000001", amount=Decimal("20"), payment_method="cash", reference=None, note=None, actor_id=999)
        await create_payment(pool, **kwargs); result = await create_payment(pool, **kwargs)
        self.assertFalse(result["created"]); self.assertEqual(result["payment"]["payment_code"], "PY000001")

    async def test_payment_rolls_back_record_and_statuses(self):
        from repositories.completions import create_handover, create_payment

        pool = FakeCompletionPool()
        await create_handover(pool, delivery_code="DL000001", recipient_type="client",
            recipient_name="Test", recipient_phone=None, note=None, actor_id=999)
        pool.conn.fail_on = "UPDATE CONSOLIDATIONS"
        with self.assertRaises(RuntimeError):
            await create_payment(pool, delivery_code="DL000001", amount=Decimal("20"),
                payment_method="cash", reference=None, note=None, actor_id=999)
        self.assertIsNone(pool.conn.payment); self.assertEqual(pool.conn.delivery["status"], "handed_over")
        self.assertEqual(pool.conn.direct_status, "handed_over")

    async def test_lists_and_payment_searches(self):
        from repositories.completions import create_handover, create_payment, get_payment, list_handovers, list_payments

        pool = FakeCompletionPool()
        await create_handover(pool, delivery_code="DL000001", recipient_type="client",
            recipient_name="Test", recipient_phone=None, note=None, actor_id=999)
        await create_payment(pool, delivery_code="DL000001", amount=Decimal("20"),
            payment_method="cash", reference=None, note=None, actor_id=999)
        self.assertEqual(len(await list_handovers(pool)), 1)
        self.assertEqual(len(await list_payments(pool)), 1)
        self.assertEqual((await get_payment(pool, "PY000001"))["payment_code"], "PY000001")
        self.assertEqual((await get_payment(pool, "DL000001"))["delivery_code"], "DL000001")


if __name__ == "__main__":
    unittest.main()
