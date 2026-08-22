import inspect
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal


def shipment(status="departed_china"):
    now = datetime.now(timezone.utc)
    return {
        "id": 1,
        "shipment_code": "SH000001",
        "transport_type": "truck",
        "transport_reference": "CN-123",
        "note": None,
        "origin_country": "CN",
        "destination_country": "TJ",
        "status": status,
        "departed_at": now,
        "created_by_telegram_id": 999,
        "created_at": now,
        "updated_at": now,
        "items_count": 2,
        "clients_count": 2,
    }


def client_item(client=1):
    return {
        "item_type": "cargo",
        "public_code": f"CG{client:06d}",
        "client_id": client,
        "telegram_user_id": 100 + client,
        "weight_kg": Decimal("2.500"),
        "volume_m3": Decimal("0.0200"),
        "pieces_count": 1,
        "tracking_numbers": [f"TRACK{client}"],
    }


class ShipmentStatusServiceTests(unittest.TestCase):
    def test_statuses_labels_and_next_status(self):
        from services.shipment_status_service import (
            SHIPMENT_STATUSES,
            next_shipment_status,
            shipment_status_label,
        )
        self.assertEqual(
            SHIPMENT_STATUSES,
            ("departed_china", "in_transit", "arrived_tajikistan",
             "customs_processing", "customs_cleared"),
        )
        self.assertEqual(next_shipment_status("departed_china"), "in_transit")
        self.assertEqual(shipment_status_label("customs_cleared"), "Таможня пройдена")

    def test_final_unknown_skip_and_backwards_are_rejected(self):
        from services.shipment_status_service import (
            FinalShipmentStatusError,
            InvalidShipmentTransitionError,
            next_shipment_status,
            validate_shipment_transition,
        )
        with self.assertRaises(FinalShipmentStatusError):
            next_shipment_status("customs_cleared")
        with self.assertRaises(InvalidShipmentTransitionError):
            next_shipment_status("unknown")
        for target in ("arrived_tajikistan", "customs_cleared"):
            with self.assertRaises(InvalidShipmentTransitionError):
                validate_shipment_transition("departed_china", target)
        with self.assertRaises(InvalidShipmentTransitionError):
            validate_shipment_transition("arrived_tajikistan", "in_transit")

    def test_note_validation(self):
        from services.shipment_status_service import validate_event_note
        self.assertIsNone(validate_event_note(" /SKIP "))
        self.assertEqual(validate_event_note("  На   границе "), "На границе")
        for value in ("x", "x" * 501):
            with self.assertRaises(ValueError):
                validate_event_note(value)

    def test_candidate_summary_and_admin_history_escape_values(self):
        from services.shipment_status_service import (
            format_advance_candidate,
            format_advance_summary,
            format_shipment_history,
        )
        row = shipment()
        row["transport_reference"] = "<CN>"
        candidate = format_advance_candidate(row, "in_transit")
        self.assertIn("SH000001", candidate)
        self.assertIn("В пути", candidate)
        data = {"shipment": row, "from_status": "departed_china",
                "to_status": "in_transit", "event_note": "<internal>"}
        self.assertIn("&lt;internal&gt;", format_advance_summary(data))
        event = {"to_status": "in_transit", "occurred_at": datetime.now(timezone.utc),
                 "created_by_telegram_id": 999, "note": "<secret>"}
        admin = format_shipment_history(row, [event], admin=True)
        client = format_shipment_history(row, [event])
        self.assertIn("999", admin)
        self.assertIn("&lt;secret&gt;", admin)
        self.assertNotIn("999", client)
        self.assertNotIn("secret", client)

    def test_notification_contains_only_one_clients_units(self):
        from services.shipment_service import build_client_views
        from services.shipment_status_service import format_status_notification
        views = build_client_views(shipment("in_transit"), [client_item(1), client_item(2)])
        event = {"to_status": "in_transit", "occurred_at": datetime.now(timezone.utc)}
        text = format_status_notification(views[0], event)
        self.assertIn("CG000001", text)
        self.assertIn("TRACK1", text)
        self.assertNotIn("CG000002", text)
        self.assertNotIn("TRACK2", text)

    def test_client_card_has_dynamic_status_and_history_without_internal_note(self):
        from services.shipment_service import build_client_views, format_client_shipment
        row = shipment("arrived_tajikistan")
        view = build_client_views(row, [client_item(1)])[0]
        view["events"] = [{"to_status": "in_transit", "occurred_at": row["departed_at"],
                           "created_by_telegram_id": 999, "note": "private"}]
        text = format_client_shipment(view)
        self.assertIn("Прибыл в Таджикистан", text)
        self.assertIn("История", text)
        self.assertNotIn("private", text)
        self.assertNotIn("999", text)


class FakeTransaction:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.snapshot = deepcopy((self.conn.row, self.conn.events, self.conn.cargo,
                                  self.conn.consolidation, self.conn.children))

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type:
            (self.conn.row, self.conn.events, self.conn.cargo,
             self.conn.consolidation, self.conn.children) = self.snapshot


class FakeAcquire:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self): return self.conn
    async def __aexit__(self, *_): pass


class FakeStatusConnection:
    def __init__(self, fail=None):
        self.row = shipment()
        self.events = []
        self.cargo = {1: "shipped_china"}
        self.consolidation = {1: "shipped_china"}
        self.children = {2: "shipped_china", 3: "shipped_china"}
        self.fail = fail
        self.queries = []

    def transaction(self): return FakeTransaction(self)

    async def fetchrow(self, query, *args):
        self.queries.append(query)
        if "FROM shipments WHERE shipment_code" in query:
            return {"id": 1, "shipment_code": "SH000001", "status": self.row["status"]}
        if "INSERT INTO shipment_events" in query:
            if self.fail == "event": raise RuntimeError("event failure")
            event = {"id": len(self.events) + 1, "shipment_id": 1,
                     "from_status": args[1], "to_status": args[2], "note": args[3],
                     "created_by_telegram_id": args[4],
                     "occurred_at": datetime.now(timezone.utc), "created_at": datetime.now(timezone.utc)}
            self.events.append(event)
            return event
        if "FROM shipment_events" in query:
            return next((x for x in self.events if x["to_status"] == args[1]), None)
        if "FROM shipments sh WHERE sh.id" in query:
            return dict(self.row)
        return None

    async def fetchval(self, query, *args):
        if "FROM consolidation_items" in query: return len(self.children)
        if "cargo_id IS NOT NULL" in query: return len(self.cargo)
        if "consolidation_id IS NOT NULL" in query: return len(self.consolidation)
        return 0

    async def execute(self, query, *args):
        if "UPDATE shipments" in query:
            if self.fail == "shipment": return "UPDATE 0"
            self.row["status"], self.row["updated_at"] = args[1], datetime.now(timezone.utc)
            return "UPDATE 1"
        if "UPDATE consolidations" in query:
            if self.fail == "consolidation": return "UPDATE 0"
            for key in self.consolidation: self.consolidation[key] = args[1]
            return f"UPDATE {len(self.consolidation)}"
        if "UPDATE cargos" in query and "SELECT ci.cargo_id" in query:
            if self.fail == "children": return "UPDATE 0"
            for key in self.children: self.children[key] = args[1]
            return f"UPDATE {len(self.children)}"
        if "UPDATE cargos" in query:
            if self.fail == "cargo": return "UPDATE 0"
            for key in self.cargo: self.cargo[key] = args[1]
            return f"UPDATE {len(self.cargo)}"
        return "UPDATE 0"


class FakePool:
    def __init__(self, fail=None): self.connection = FakeStatusConnection(fail)
    def acquire(self): return FakeAcquire(self.connection)


async def advance(pool, expected="departed_china"):
    from repositories.shipments import advance_shipment_status
    return await advance_shipment_status(
        pool, shipment_code="SH000001", expected_from_status=expected,
        note="Border", created_by_telegram_id=999,
    )


class ShipmentStatusRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_transaction_creates_event_and_updates_every_object(self):
        pool = FakePool()
        result = await advance(pool)
        self.assertTrue(result["created"])
        self.assertEqual(pool.connection.row["status"], "in_transit")
        self.assertEqual(len(pool.connection.events), 1)
        self.assertTrue(all(x == "in_transit" for x in pool.connection.cargo.values()))
        self.assertTrue(all(x == "in_transit" for x in pool.connection.consolidation.values()))
        self.assertTrue(all(x == "in_transit" for x in pool.connection.children.values()))
        self.assertTrue(any("FOR UPDATE" in q for q in pool.connection.queries))

    async def test_repeated_confirmation_returns_existing_event(self):
        pool = FakePool()
        first = await advance(pool)
        second = await advance(pool)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(len(pool.connection.events), 1)

    async def test_all_failures_roll_back(self):
        from repositories.shipments import ShipmentStatusChangedError
        for failure, error in (("event", RuntimeError), ("shipment", ShipmentStatusChangedError),
                               ("cargo", ShipmentStatusChangedError),
                               ("consolidation", ShipmentStatusChangedError),
                               ("children", ShipmentStatusChangedError)):
            with self.subTest(failure=failure):
                pool = FakePool(failure)
                with self.assertRaises(error): await advance(pool)
                self.assertEqual(pool.connection.row["status"], "departed_china")
                self.assertEqual(pool.connection.events, [])

    def test_repository_has_lock_and_server_side_transition(self):
        from repositories.shipments import advance_shipment_status
        source = inspect.getsource(advance_shipment_status)
        self.assertIn("FOR UPDATE", source)
        self.assertIn("next_shipment_status(expected_from_status)", source)


class ShipmentStatusIntegrationTests(unittest.TestCase):
    def test_migration_order_and_dispatcher(self):
        from bot_app import create_dispatcher
        from migrations.runner import MIGRATIONS_DIR
        self.assertIn("include_router(shipment.router)", inspect.getsource(create_dispatcher))
        self.assertEqual(
            [path.name for path in sorted(MIGRATIONS_DIR.glob("*.sql"))],
            ["001_create_orders.sql", "002_create_clients.sql", "003_create_china_trackings.sql",
             "004_create_cargos.sql", "005_create_consolidations.sql",
             "006_create_shipments.sql", "007_create_shipment_events.sql"],
        )


if __name__ == "__main__":
    unittest.main()
