import inspect
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal


def cargo(code="CG000001", *, status="received_china", client=1, shipment_id=None,
          parent=None):
    return {
        "item_type": "cargo", "item_id": int(code[2:]), "public_code": code,
        "client_id": client, "weight_kg": Decimal("2.500"),
        "volume_m3": Decimal("0.0200"), "pieces_count": 1, "status": status,
        "client_code": f"C{client:06d}", "telegram_user_id": 100 + client,
        "full_name": f"Client {client}", "tracking_numbers": [f"TRACK{code[2:]}"],
        "parent_consolidation_id": parent, "parent_consolidation_code": "CS000009" if parent else None,
        "shipment_id": shipment_id, "shipment_code": "SH000009" if shipment_id else None,
    }


def consolidation(code="CS000001", *, status="consolidated_china", client=2,
                  shipment_id=None):
    return {
        "item_type": "consolidation", "item_id": int(code[2:]), "public_code": code,
        "client_id": client, "weight_kg": Decimal("4.000"),
        "volume_m3": Decimal("0.0300"), "pieces_count": 2, "status": status,
        "client_code": f"C{client:06d}", "telegram_user_id": 100 + client,
        "full_name": f"Client {client}", "tracking_numbers": ["TRACKA", "TRACKB"],
        "parent_consolidation_id": None, "parent_consolidation_code": None,
        "shipment_id": shipment_id, "shipment_code": "SH000009" if shipment_id else None,
    }


class ShipmentServiceTests(unittest.TestCase):
    def test_code_format_and_normalization(self):
        from services.shipment_service import format_shipment_code, normalize_shipment_code
        self.assertEqual(format_shipment_code(1), "SH000001")
        self.assertEqual(normalize_shipment_code(" sh000001 "), "SH000001")
        for bad in ("SH1", "CG000001", "SHABC"):
            with self.assertRaises(ValueError): normalize_shipment_code(bad)

    def test_mixed_codes_normalization_dedup_and_limits(self):
        from services.shipment_service import parse_dispatch_codes
        self.assertEqual(parse_dispatch_codes("cg000001, CS000002 cg000001"), ["CG000001", "CS000002"])
        with self.assertRaises(ValueError): parse_dispatch_codes("")
        with self.assertRaises(ValueError): parse_dispatch_codes("XX000001")
        with self.assertRaises(ValueError): parse_dispatch_codes(" ".join(f"CG{i:06d}" for i in range(1, 202)))

    def test_totals_with_and_without_complete_volume(self):
        from services.shipment_service import shipment_totals
        values = [cargo(), consolidation()]
        totals = shipment_totals(values)
        self.assertEqual(totals["weight_kg"], Decimal("6.500"))
        self.assertEqual(totals["volume_m3"], Decimal("0.0500"))
        self.assertEqual(totals["pieces_count"], 3)
        values[1]["volume_m3"] = None
        self.assertIsNone(shipment_totals(values)["volume_m3"])

    def test_transport_reference_and_note_validation(self):
        from services.shipment_service import validate_note, validate_reference, validate_transport_type
        for value in ("truck", "air", "rail", "other"):
            self.assertEqual(validate_transport_type(value), value)
        with self.assertRaises(ValueError): validate_transport_type("ship")
        self.assertIsNone(validate_reference("/skip"))
        self.assertEqual(validate_reference(" CN  123 "), "CN 123")
        self.assertIsNone(validate_note(" /SKIP "))
        with self.assertRaises(ValueError): validate_reference("x")
        with self.assertRaises(ValueError): validate_note("x" * 501)

    def test_cards_and_client_privacy(self):
        from services.shipment_service import (
            build_client_views, format_admin_shipment, format_client_shipment,
            format_dispatch_candidate, format_dispatch_summary,
        )
        items = [cargo(), consolidation()]
        data = {"items": items, "transport_type": "truck", "transport_reference": "<CN1>", "note": "<ok>"}
        self.assertIn("CG000001", format_dispatch_candidate(items))
        self.assertIn("Shipment ID", format_dispatch_summary(data))
        shipment = {"id": 1, "shipment_code": "SH000001", "transport_type": "truck",
                    "transport_reference": "<CN1>", "departed_at": datetime.now(timezone.utc),
                    "items_count": 2, "clients_count": 2}
        views = build_client_views(shipment, items)
        self.assertEqual(len(views), 2)
        client_text = format_client_shipment(views[0], notification=True)
        self.assertIn("CG000001", client_text)
        self.assertNotIn("CS000001", client_text)
        self.assertNotIn("Client 2", client_text)
        self.assertNotIn("<CN1>", client_text)
        self.assertIn("&lt;CN1&gt;", client_text)
        self.assertIn("SH000001", format_admin_shipment(shipment, details=items))

    def test_client_rows_are_grouped_by_shipment(self):
        from services.shipment_service import group_client_shipment_units
        rows = []
        for item in (cargo("CG000001"), cargo("CG000002")):
            rows.append({**item, "id": 1, "shipment_code": "SH000001", "transport_type": "air",
                         "transport_reference": None, "departed_at": datetime.now(timezone.utc)})
        views = group_client_shipment_units(rows)
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0]["cargo_codes"], ["CG000001", "CG000002"])


class ShipmentValidationTests(unittest.TestCase):
    def test_unknown_object(self):
        from repositories.shipments import DispatchObjectNotFoundError, validate_dispatch_items
        with self.assertRaises(DispatchObjectNotFoundError): validate_dispatch_items(["CG000001"], [])

    def test_cargo_inside_consolidation(self):
        from repositories.shipments import CargoInConsolidationError, validate_dispatch_items
        with self.assertRaises(CargoInConsolidationError): validate_dispatch_items(["CG000001"], [cargo(parent=9)])

    def test_already_shipped_cargo_and_consolidation(self):
        from repositories.shipments import DispatchObjectAlreadyShippedError, validate_dispatch_items
        for row in (cargo(shipment_id=9), consolidation(shipment_id=9)):
            with self.assertRaises(DispatchObjectAlreadyShippedError): validate_dispatch_items([row["public_code"]], [row])

    def test_wrong_status(self):
        from repositories.shipments import DispatchObjectUnavailableError, validate_dispatch_items
        for row in (cargo(status="consolidated"), consolidation(status="shipped_china")):
            with self.assertRaises(DispatchObjectUnavailableError): validate_dispatch_items([row["public_code"]], [row])


class FakeTransaction:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self):
        self.snapshot = deepcopy((self.conn.shipments, self.conn.items, self.conn.cargo_status,
                                  self.conn.consolidation_status, self.conn.child_status))
    async def __aexit__(self, exc_type, exc, tb):
        if exc_type:
            (self.conn.shipments, self.conn.items, self.conn.cargo_status,
             self.conn.consolidation_status, self.conn.child_status) = self.snapshot


class FakeAcquire:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self): return self.conn
    async def __aexit__(self, *_): pass


class FakeShipmentConnection:
    def __init__(self, *, fail_item=False, fail_cargo=False, fail_consolidation=False):
        self.candidates = [cargo(), consolidation()]
        self.shipments, self.items = {}, []
        self.cargo_status = {1: "received_china"}
        self.consolidation_status = {1: "consolidated_china"}
        self.child_status = {10: "consolidated", 11: "consolidated"}
        self.fail_item, self.fail_cargo, self.fail_consolidation = fail_item, fail_cargo, fail_consolidation

    def transaction(self): return FakeTransaction(self)

    async def fetch(self, query, *args):
        codes = set(args[0]) if args else set()
        if "FROM cargos cg JOIN" in query:
            return [x for x in self.candidates if x["item_type"] == "cargo" and x["public_code"] in codes]
        if "FROM consolidations cs JOIN" in query:
            return [x for x in self.candidates if x["item_type"] == "consolidation" and x["public_code"] in codes]
        return []

    async def fetchrow(self, query, *args):
        if "INSERT INTO shipments" in query:
            row = {"id": 1, "shipment_code": "SH000001"}
            self.shipments[1] = {**row, "transport_type": args[0], "transport_reference": args[1],
                                 "note": args[2], "departed_at": datetime.now(timezone.utc),
                                 "items_count": len(self.items), "clients_count": 2}
            return row
        if "WHERE sh.id = $1" in query: return self.shipments.get(args[0])
        return None

    async def fetchval(self, query, *args): return len(self.child_status)

    async def execute(self, query, *args):
        if "INSERT INTO shipment_items" in query:
            if self.fail_item: raise RuntimeError("item failure")
            self.items.append(args)
            return "INSERT 0 1"
        if "UPDATE cargos SET status='shipped_china'" in query and "SELECT cargo_id" not in query:
            if self.fail_cargo: return "UPDATE 0"
            for item_id in args[0]: self.cargo_status[item_id] = "shipped_china"
            return f"UPDATE {len(args[0])}"
        if "UPDATE consolidations" in query:
            if self.fail_consolidation: return "UPDATE 0"
            for item_id in args[0]: self.consolidation_status[item_id] = "shipped_china"
            return f"UPDATE {len(args[0])}"
        if "SELECT cargo_id FROM consolidation_items" in query:
            for item_id in self.child_status: self.child_status[item_id] = "shipped_china"
            return f"UPDATE {len(self.child_status)}"
        return "UPDATE 0"


class FakeShipmentPool:
    def __init__(self, **kwargs): self.connection = FakeShipmentConnection(**kwargs)
    def acquire(self): return FakeAcquire(self.connection)


async def create_test_shipment(pool):
    from repositories.shipments import create_shipment
    return await create_shipment(
        pool, codes=["CG000001", "CS000001"], transport_type="truck",
        transport_reference="CN-1", note=None, created_by_telegram_id=999,
    )


class ShipmentRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_transaction_creates_mixed_items_and_updates_all_statuses(self):
        pool = FakeShipmentPool()
        result = await create_test_shipment(pool)
        self.assertEqual(result["shipment_code"], "SH000001")
        self.assertEqual(len(pool.connection.items), 2)
        self.assertEqual(pool.connection.cargo_status[1], "shipped_china")
        self.assertEqual(pool.connection.consolidation_status[1], "shipped_china")
        self.assertTrue(all(x == "shipped_china" for x in pool.connection.child_status.values()))

    async def test_repeated_confirmation_returns_existing(self):
        pool = FakeShipmentPool()
        first = await create_test_shipment(pool)
        for row in pool.connection.candidates:
            row["shipment_id"], row["shipment_code"] = 1, "SH000001"
        second = await create_test_shipment(pool)
        self.assertEqual(first["shipment_code"], second["shipment_code"])
        self.assertEqual(len(pool.connection.shipments), 1)

    async def test_item_failure_rolls_back(self):
        pool = FakeShipmentPool(fail_item=True)
        with self.assertRaises(RuntimeError): await create_test_shipment(pool)
        self.assertEqual(pool.connection.shipments, {})

    async def test_cargo_update_failure_rolls_back(self):
        from repositories.shipments import DispatchObjectUnavailableError
        pool = FakeShipmentPool(fail_cargo=True)
        with self.assertRaises(DispatchObjectUnavailableError): await create_test_shipment(pool)
        self.assertEqual(pool.connection.shipments, {})
        self.assertEqual(pool.connection.cargo_status[1], "received_china")

    async def test_consolidation_update_failure_rolls_back(self):
        from repositories.shipments import DispatchObjectUnavailableError
        pool = FakeShipmentPool(fail_consolidation=True)
        with self.assertRaises(DispatchObjectUnavailableError): await create_test_shipment(pool)
        self.assertEqual(pool.connection.shipments, {})
        self.assertEqual(pool.connection.consolidation_status[1], "consolidated_china")

    def test_repository_uses_locks_transaction_and_no_max(self):
        from repositories.shipments import create_shipment
        source = inspect.getsource(create_shipment).upper()
        self.assertIn("TRANSACTION", source)
        self.assertIn("LOCK=TRUE", source)
        self.assertNotIn("MAX(", source)


class ShipmentIntegrationTests(unittest.TestCase):
    def test_dispatcher_and_migrations(self):
        from bot_app import create_dispatcher
        from migrations.runner import MIGRATIONS_DIR
        self.assertIn("include_router(shipment.router)", inspect.getsource(create_dispatcher))
        self.assertEqual(
            [x.name for x in sorted(MIGRATIONS_DIR.glob("*.sql"))],
            ["001_create_orders.sql", "002_create_clients.sql", "003_create_china_trackings.sql",
             "004_create_cargos.sql", "005_create_consolidations.sql", "006_create_shipments.sql",
             "007_create_shipment_events.sql", "008_create_pickup_deliveries.sql"],
        )

    def test_repository_public_queries_exist(self):
        from repositories import shipments
        for name in ("list_recent_shipments", "get_shipment_by_code", "list_client_shipment_units"):
            self.assertTrue(inspect.iscoroutinefunction(getattr(shipments, name)))


if __name__ == "__main__":
    unittest.main()
