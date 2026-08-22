import copy
import unittest
from datetime import datetime, timezone
from decimal import Decimal


class AcquireContext:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeTransaction:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        self.snapshot = copy.deepcopy(
            (self.connection.tracking, self.connection.cargos, self.connection.photos)
        )
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            (
                self.connection.tracking,
                self.connection.cargos,
                self.connection.photos,
            ) = self.snapshot
        return False


class FakeCargoConnection:
    def __init__(self, tracking_status="declared", fail_photo_position=None):
        now = datetime(2026, 8, 22, 12, 30, tzinfo=timezone.utc)
        self.tracking = {
            "id": 10,
            "client_id": 1,
            "tracking_number": "LP123456789CN",
            "tracking_number_normalized": "LP123456789CN",
            "status": tracking_status,
            "created_at": now,
            "updated_at": now,
        }
        self.client = {
            "id": 1,
            "client_code": "C000001",
            "telegram_user_id": 101,
            "telegram_username": "client",
            "full_name": "Test Client",
            "phone": "+992900001122",
            "delivery_city": "Душанбе",
        }
        self.cargos = {}
        self.photos = []
        self.fail_photo_position = fail_photo_position

    def transaction(self):
        return FakeTransaction(self)

    def _cargo_row(self, cargo):
        return {
            **cargo,
            "tracking_number": self.tracking["tracking_number"],
            "tracking_number_normalized": self.tracking["tracking_number_normalized"],
            "client_code": self.client["client_code"],
            "telegram_user_id": self.client["telegram_user_id"],
            "telegram_username": self.client["telegram_username"],
            "full_name": self.client["full_name"],
            "phone": self.client["phone"],
            "delivery_city": self.client["delivery_city"],
            "photos_count": len(
                [photo for photo in self.photos if photo["cargo_id"] == cargo["id"]]
            ),
        }

    def _receipt_row(self):
        cargo = next(iter(self.cargos.values()), None)
        return {
            **self.tracking,
            **{key: value for key, value in self.client.items() if key != "id"},
            "cargo_id": cargo["id"] if cargo else None,
            "cargo_code": cargo["cargo_code"] if cargo else None,
        }

    async def fetchrow(self, query, *args):
        compact = " ".join(query.split())
        if "FOR UPDATE OF t" in compact:
            if args[0] != self.tracking["id"]:
                return None
            cargo = next(iter(self.cargos.values()), None)
            return {
                "id": self.tracking["id"],
                "client_id": self.tracking["client_id"],
                "status": self.tracking["status"],
                "cargo_id": cargo["id"] if cargo else None,
            }
        if "LEFT JOIN cargos cg" in compact and "FROM china_trackings t" in compact:
            if "tracking_number_normalized = $1" in compact:
                return self._receipt_row() if args[0] == self.tracking["tracking_number_normalized"] else None
            return self._receipt_row() if args[0] == self.tracking["id"] else None
        if compact.startswith("INSERT INTO cargos"):
            cargo_id = len(self.cargos) + 1
            now = datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc)
            cargo = {
                "id": cargo_id,
                "cargo_code": f"CG{cargo_id:06d}",
                "client_id": args[0],
                "china_tracking_id": args[1],
                "description": args[2],
                "actual_weight_kg": args[3],
                "volume_m3": args[4],
                "pieces_count": args[5],
                "status": "received_china",
                "received_at": now,
                "received_by_telegram_id": args[6],
                "created_at": now,
                "updated_at": now,
            }
            self.cargos[cargo_id] = cargo
            return {"id": cargo_id, "cargo_code": cargo["cargo_code"]}
        if "FROM cargos cg" in compact:
            if "WHERE cg.id = $1" in compact:
                cargo = self.cargos.get(args[0])
            else:
                cargo = next(
                    (item for item in self.cargos.values() if item["cargo_code"] == args[0]),
                    None,
                )
                if cargo and "c.telegram_user_id = $2" in compact and args[1] != self.client["telegram_user_id"]:
                    return None
            return self._cargo_row(cargo) if cargo else None
        raise AssertionError(f"Unexpected fetchrow query: {compact}")

    async def execute(self, query, *args):
        compact = " ".join(query.split())
        if compact.startswith("INSERT INTO cargo_photos"):
            if self.fail_photo_position == args[3]:
                raise RuntimeError("simulated photo insert failure")
            self.photos.append(
                {
                    "cargo_id": args[0],
                    "telegram_file_id": args[1],
                    "telegram_file_unique_id": args[2],
                    "position": args[3],
                }
            )
            return "INSERT 0 1"
        if compact.startswith("UPDATE china_trackings"):
            if self.tracking["status"] != "declared":
                return "UPDATE 0"
            self.tracking["status"] = "received"
            return "UPDATE 1"
        raise AssertionError(f"Unexpected execute query: {compact}")

    async def fetch(self, query, *args):
        compact = " ".join(query.split())
        if compact.startswith("SELECT telegram_file_id"):
            return sorted(
                [photo for photo in self.photos if photo["cargo_id"] == args[0]],
                key=lambda photo: photo["position"],
            )
        if "FROM cargos cg" in compact:
            rows = [self._cargo_row(cargo) for cargo in self.cargos.values()]
            if "WHERE cg.client_id = $1" in compact:
                rows = [row for row in rows if row["client_id"] == args[0]]
                limit = args[1]
            else:
                limit = args[0]
            return rows[:limit]
        raise AssertionError(f"Unexpected fetch query: {compact}")


class FakeCargoPool:
    def __init__(self, tracking_status="declared", fail_photo_position=None):
        self.connection = FakeCargoConnection(tracking_status, fail_photo_position)

    def acquire(self):
        return AcquireContext(self.connection)


def photo(number):
    return {"file_id": f"file-{number}", "file_unique_id": f"unique-{number}"}


async def create_test_cargo(pool, photos=None):
    from repositories.cargos import create_cargo_from_tracking

    return await create_cargo_from_tracking(
        pool,
        tracking_id=10,
        description="Одежда",
        actual_weight_kg=Decimal("2.500"),
        volume_m3=Decimal("0.0350"),
        pieces_count=1,
        photos=[photo(1)] if photos is None else photos,
        received_by_telegram_id=999,
    )


class CargoServiceTests(unittest.TestCase):
    def test_weight_supports_dot_and_comma(self):
        from services.cargo_service import parse_weight

        self.assertEqual(parse_weight("2.5"), Decimal("2.5"))
        self.assertEqual(parse_weight("2,5"), Decimal("2.5"))

    def test_weight_rejects_zero_negative_maximum_and_precision(self):
        from services.cargo_service import parse_weight

        for value in ("0", "-1", "1000000", "2.1234", "NaN", "Infinity"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_weight(value)

    def test_volume_and_skip(self):
        from services.cargo_service import parse_volume

        self.assertEqual(parse_volume("0,035"), Decimal("0.035"))
        self.assertIsNone(parse_volume("/skip"))
        for value in ("0", "10000", "1.12345"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_volume(value)

    def test_pieces_count(self):
        from services.cargo_service import parse_pieces_count

        self.assertEqual(parse_pieces_count("1"), 1)
        self.assertEqual(parse_pieces_count("10000"), 10000)
        for value in ("0", "10001", "1.5", "-1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_pieces_count(value)

    def test_description_and_skip(self):
        from services.cargo_service import validate_description

        self.assertEqual(validate_description("  Детская   одежда "), "Детская одежда")
        self.assertIsNone(validate_description("/skip"))
        for value in ("x", "x" * 501):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_description(value)

    def test_photo_limits_and_duplicates(self):
        from services.cargo_service import validate_photos

        validate_photos([photo(1)])
        validate_photos([photo(i) for i in range(10)])
        for photos in ([], [photo(i) for i in range(11)], [photo(1), photo(1)]):
            with self.subTest(count=len(photos)), self.assertRaises(ValueError):
                validate_photos(photos)

    def test_cargo_code(self):
        from services.cargo_service import format_cargo_code, normalize_cargo_code

        self.assertEqual(format_cargo_code(1), "CG000001")
        self.assertEqual(normalize_cargo_code(" cg000001 "), "CG000001")

    def test_all_formatters_hide_internal_ids_and_escape_description(self):
        from services.cargo_service import (
            format_admin_cargo,
            format_client_cargo,
            format_client_notification,
            format_receipt_summary,
        )

        cargo = {
            "id": 777,
            "cargo_code": "CG000001",
            "tracking_number": "LP123456789CN",
            "client_code": "C000001",
            "full_name": "Test Client",
            "phone": "+992900001122",
            "delivery_city": "Душанбе",
            "description": "<одежда>",
            "actual_weight_kg": Decimal("2.5"),
            "volume_m3": None,
            "pieces_count": 1,
            "photos_count": 1,
            "received_at": datetime(2026, 8, 22, tzinfo=timezone.utc),
        }
        for text in (
            format_client_notification(cargo),
            format_client_cargo(cargo),
            format_admin_cargo(cargo, full=True),
        ):
            self.assertIn("CG000001", text)
            self.assertNotIn("777", text)
            self.assertNotIn("<одежда>", text)
        summary = format_receipt_summary({**cargo, "photos": [photo(1)]})
        self.assertIn("LP123456789CN", summary)
        self.assertNotIn("<одежда>", summary)


class CargoRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_repository_uses_lock_and_never_max_plus_one(self):
        import inspect

        from repositories.cargos import create_cargo_from_tracking

        source = inspect.getsource(create_cargo_from_tracking).upper()
        self.assertIn("FOR UPDATE", source)
        self.assertNotIn("MAX(", source)

    async def test_repository_rejects_zero_and_eleven_photos(self):
        for photos in ([], [photo(i) for i in range(11)]):
            with self.subTest(count=len(photos)), self.assertRaises(ValueError):
                await create_test_cargo(FakeCargoPool(), photos)

    async def test_transaction_creates_cargo_photos_and_receives_tracking(self):
        pool = FakeCargoPool()
        cargo = await create_test_cargo(pool, [photo(1), photo(2)])
        self.assertEqual(cargo["cargo_code"], "CG000001")
        self.assertEqual(pool.connection.tracking["status"], "received")
        self.assertEqual(len(pool.connection.photos), 2)

    async def test_transaction_saves_ten_photos(self):
        pool = FakeCargoPool()
        await create_test_cargo(pool, [photo(i) for i in range(10)])
        self.assertEqual(len(pool.connection.photos), 10)

    async def test_repeated_creation_returns_same_cargo(self):
        pool = FakeCargoPool()
        first = await create_test_cargo(pool)
        second = await create_test_cargo(pool)
        self.assertEqual(first["cargo_code"], second["cargo_code"])
        self.assertEqual(len(pool.connection.cargos), 1)

    async def test_cancelled_and_received_tracking_are_rejected(self):
        from repositories.cargos import (
            TrackingAlreadyReceivedError,
            TrackingCancelledError,
        )

        with self.assertRaises(TrackingCancelledError):
            await create_test_cargo(FakeCargoPool("cancelled"))
        with self.assertRaises(TrackingAlreadyReceivedError):
            await create_test_cargo(FakeCargoPool("received"))

    async def test_photo_failure_rolls_back_everything(self):
        pool = FakeCargoPool(fail_photo_position=2)
        with self.assertRaises(RuntimeError):
            await create_test_cargo(pool, [photo(1), photo(2)])
        self.assertEqual(pool.connection.tracking["status"], "declared")
        self.assertEqual(pool.connection.cargos, {})
        self.assertEqual(pool.connection.photos, [])

    async def test_receipt_lookup_by_number(self):
        from repositories.cargos import get_receipt_tracking_by_number

        pool = FakeCargoPool()
        found = await get_receipt_tracking_by_number(pool, "LP123456789CN")
        missing = await get_receipt_tracking_by_number(pool, "NOTFOUND")
        self.assertEqual(found["client_code"], "C000001")
        self.assertIsNone(missing)

    async def test_owner_can_get_cargo_but_other_user_cannot(self):
        from repositories.cargos import get_client_cargo_by_code

        pool = FakeCargoPool()
        await create_test_cargo(pool)
        owned = await get_client_cargo_by_code(pool, 101, "CG000001")
        foreign = await get_client_cargo_by_code(pool, 202, "CG000001")
        self.assertIsNotNone(owned)
        self.assertIsNone(foreign)

    async def test_client_and_admin_lists_and_code_search(self):
        from repositories.cargos import (
            get_cargo_by_code,
            list_client_cargos,
            list_recent_cargos,
        )

        pool = FakeCargoPool()
        await create_test_cargo(pool)
        self.assertEqual(len(await list_client_cargos(pool, 1)), 1)
        self.assertEqual(len(await list_recent_cargos(pool)), 1)
        self.assertEqual((await get_cargo_by_code(pool, "CG000001"))["client_code"], "C000001")

    async def test_photos_are_returned_in_position_order(self):
        from repositories.cargos import get_cargo_photos

        pool = FakeCargoPool()
        cargo = await create_test_cargo(pool, [photo(1), photo(2), photo(3)])
        photos = await get_cargo_photos(pool, cargo["id"])
        self.assertEqual([item["position"] for item in photos], [1, 2, 3])


class CargoIntegrationSmokeTests(unittest.TestCase):
    def test_dispatcher_includes_cargo_and_warehouse_routers(self):
        import inspect

        from bot_app import create_dispatcher

        source = inspect.getsource(create_dispatcher)
        self.assertIn("include_router(cargo.router)", source)
        self.assertIn("include_router(warehouse.router)", source)

    def test_migration_004_follows_existing_migrations(self):
        from migrations.runner import MIGRATIONS_DIR

        names = [path.name for path in sorted(MIGRATIONS_DIR.glob("*.sql"))]
        self.assertEqual(
            names,
            [
                "001_create_orders.sql",
                "002_create_clients.sql",
                "003_create_china_trackings.sql",
                "004_create_cargos.sql",
                "005_create_consolidations.sql",
                "006_create_shipments.sql",
                "007_create_shipment_events.sql",
            ],
        )


if __name__ == "__main__":
    unittest.main()
