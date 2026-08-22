import copy
import inspect
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
            (
                self.connection.cargos,
                self.connection.consolidations,
                self.connection.items,
                self.connection.photos,
            )
        )
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            (
                self.connection.cargos,
                self.connection.consolidations,
                self.connection.items,
                self.connection.photos,
            ) = self.snapshot
        return False


class FakeConsolidationConnection:
    def __init__(self, fail_item=None, fail_photo=None, fail_update=False):
        now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        self.clients = {
            1: {
                "client_code": "C000001",
                "telegram_user_id": 101,
                "telegram_username": "first",
                "full_name": "First Client",
                "phone": "+992900001111",
                "delivery_city": "Душанбе",
            },
            2: {
                "client_code": "C000002",
                "telegram_user_id": 202,
                "telegram_username": "second",
                "full_name": "Second Client",
                "phone": "+992900002222",
                "delivery_city": "Худжанд",
            },
        }
        self.cargos = {
            1: self._cargo(1, 1, "CG000001", "TRACK001", now),
            2: self._cargo(2, 1, "CG000002", "TRACK002", now),
            3: self._cargo(3, 2, "CG000003", "TRACK003", now),
        }
        self.consolidations = {}
        self.items = []
        self.photos = []
        self.fail_item = fail_item
        self.fail_photo = fail_photo
        self.fail_update = fail_update

    @staticmethod
    def _cargo(cargo_id, client_id, code, tracking, now):
        return {
            "id": cargo_id,
            "cargo_code": code,
            "client_id": client_id,
            "actual_weight_kg": Decimal("2.500"),
            "volume_m3": Decimal("0.0350"),
            "pieces_count": 1,
            "status": "received_china",
            "tracking_number": tracking,
            "updated_at": now,
        }

    def transaction(self):
        return FakeTransaction(self)

    def _candidate(self, cargo):
        item = next((item for item in self.items if item["cargo_id"] == cargo["id"]), None)
        consolidation = self.consolidations.get(item["consolidation_id"]) if item else None
        return {
            **cargo,
            **self.clients[cargo["client_id"]],
            "consolidation_id": item["consolidation_id"] if item else None,
            "consolidation_code": consolidation["consolidation_code"] if consolidation else None,
        }

    def _consolidation_row(self, consolidation):
        items = sorted(
            [item for item in self.items if item["consolidation_id"] == consolidation["id"]],
            key=lambda item: item["position"],
        )
        cargos = [self.cargos[item["cargo_id"]] for item in items]
        return {
            **consolidation,
            **self.clients[consolidation["client_id"]],
            "cargo_codes": [cargo["cargo_code"] for cargo in cargos],
            "tracking_numbers": [cargo["tracking_number"] for cargo in cargos],
            "photos_count": len(
                [photo for photo in self.photos if photo["consolidation_id"] == consolidation["id"]]
            ),
        }

    async def fetch(self, query, *args):
        compact = " ".join(query.split())
        if "FROM cargos cg" in compact and "ANY($1::text[])" in compact:
            codes = args[0]
            rows = [self._candidate(cargo) for cargo in self.cargos.values() if cargo["cargo_code"] in codes]
            if "ORDER BY cg.id" in compact:
                return sorted(rows, key=lambda row: row["id"])
            by_code = {row["cargo_code"]: row for row in rows}
            return [by_code[code] for code in codes if code in by_code]
        if compact.startswith("SELECT telegram_file_id"):
            return sorted(
                [photo for photo in self.photos if photo["consolidation_id"] == args[0]],
                key=lambda photo: photo["position"],
            )
        if "FROM consolidations cs" in compact:
            rows = [self._consolidation_row(row) for row in self.consolidations.values()]
            if "WHERE cs.client_id = $1" in compact:
                rows = [row for row in rows if row["client_id"] == args[0]]
                limit = args[1]
            else:
                limit = args[0]
            return rows[:limit]
        raise AssertionError(f"Unexpected fetch: {compact}")

    async def fetchrow(self, query, *args):
        compact = " ".join(query.split())
        if compact.startswith("INSERT INTO consolidations"):
            consolidation_id = len(self.consolidations) + 1
            now = datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc)
            row = {
                "id": consolidation_id,
                "consolidation_code": f"CS{consolidation_id:06d}",
                "client_id": args[0],
                "description": args[1],
                "final_weight_kg": args[2],
                "final_volume_m3": args[3],
                "final_pieces_count": args[4],
                "status": "consolidated_china",
                "consolidated_at": now,
                "consolidated_by_telegram_id": args[5],
                "created_at": now,
                "updated_at": now,
            }
            self.consolidations[consolidation_id] = row
            return {"id": consolidation_id, "consolidation_code": row["consolidation_code"]}
        if "FROM consolidation_items ci" in compact and "WHERE cg.cargo_code = $1" in compact:
            cargo = next((cargo for cargo in self.cargos.values() if cargo["cargo_code"] == args[0]), None)
            item = next((item for item in self.items if cargo and item["cargo_id"] == cargo["id"]), None)
            row = self.consolidations.get(item["consolidation_id"]) if item else None
            return self._consolidation_row(row) if row else None
        if "FROM consolidations cs" in compact:
            if "WHERE cs.id = $1" in compact:
                row = self.consolidations.get(args[0])
            else:
                row = next(
                    (row for row in self.consolidations.values() if row["consolidation_code"] == args[0]),
                    None,
                )
                if row and "c.telegram_user_id = $2" in compact and args[1] != self.clients[row["client_id"]]["telegram_user_id"]:
                    return None
            return self._consolidation_row(row) if row else None
        raise AssertionError(f"Unexpected fetchrow: {compact}")

    async def execute(self, query, *args):
        compact = " ".join(query.split())
        if compact.startswith("INSERT INTO consolidation_items"):
            if self.fail_item == args[2]:
                raise RuntimeError("simulated item failure")
            self.items.append(
                {"consolidation_id": args[0], "cargo_id": args[1], "position": args[2]}
            )
            return "INSERT 0 1"
        if compact.startswith("INSERT INTO consolidation_photos"):
            if self.fail_photo == args[3]:
                raise RuntimeError("simulated photo failure")
            self.photos.append(
                {
                    "consolidation_id": args[0],
                    "telegram_file_id": args[1],
                    "telegram_file_unique_id": args[2],
                    "position": args[3],
                }
            )
            return "INSERT 0 1"
        if compact.startswith("UPDATE cargos"):
            if self.fail_update:
                return "UPDATE 0"
            updated = 0
            for cargo_id in args[0]:
                if self.cargos[cargo_id]["status"] == "received_china":
                    self.cargos[cargo_id]["status"] = "consolidated"
                    updated += 1
            return f"UPDATE {updated}"
        raise AssertionError(f"Unexpected execute: {compact}")


class FakeConsolidationPool:
    def __init__(self, **kwargs):
        self.connection = FakeConsolidationConnection(**kwargs)

    def acquire(self):
        return AcquireContext(self.connection)


def photo(number):
    return {"file_id": f"file-{number}", "file_unique_id": f"unique-{number}"}


async def create_test_consolidation(pool, codes=None, photos=None):
    from repositories.consolidations import create_consolidation

    return await create_consolidation(
        pool,
        cargo_codes=codes or ["CG000001", "CG000002"],
        description="Одна коробка",
        final_weight_kg=Decimal("4.700"),
        final_volume_m3=Decimal("0.0600"),
        final_pieces_count=1,
        photos=[photo(1)] if photos is None else photos,
        consolidated_by_telegram_id=999,
    )


class ConsolidationServiceTests(unittest.TestCase):
    def test_code_format_and_normalization(self):
        from services.consolidation_service import (
            format_consolidation_code,
            normalize_consolidation_code,
        )

        self.assertEqual(format_consolidation_code(1), "CS000001")
        self.assertEqual(normalize_consolidation_code(" cs000001 "), "CS000001")

    def test_cargo_codes_are_normalized_and_deduplicated(self):
        from services.consolidation_service import parse_cargo_codes

        self.assertEqual(
            parse_cargo_codes("cg000001, CG000001 CG000002"),
            ["CG000001", "CG000002"],
        )

    def test_cargo_code_count_is_limited(self):
        from services.consolidation_service import parse_cargo_codes

        with self.assertRaises(ValueError):
            parse_cargo_codes("CG000001")
        with self.assertRaises(ValueError):
            parse_cargo_codes(" ".join(f"CG{i:06d}" for i in range(1, 52)))

    def test_candidate_contains_totals(self):
        from services.consolidation_service import format_consolidation_candidate

        pool = FakeConsolidationPool()
        rows = [pool.connection._candidate(pool.connection.cargos[index]) for index in (1, 2)]
        text = format_consolidation_candidate(rows)
        self.assertIn("5.000", text)
        self.assertIn("0.0700", text)
        self.assertIn("CG000001", text)

    def test_summary_notification_and_cards(self):
        from services.consolidation_service import (
            format_admin_consolidation,
            format_client_consolidation,
            format_client_notification,
            format_consolidation_summary,
        )

        now = datetime(2026, 8, 22, tzinfo=timezone.utc)
        row = {
            "id": 999,
            "consolidation_code": "CS000001",
            "client_code": "C000001",
            "full_name": "Test Client",
            "phone": "+992900001122",
            "delivery_city": "Душанбе",
            "cargo_codes": ["CG000001", "CG000002"],
            "tracking_numbers": ["TRACK001", "TRACK002"],
            "description": "<коробка>",
            "final_weight_kg": Decimal("4.7"),
            "final_volume_m3": None,
            "final_pieces_count": 1,
            "photos": [photo(1)],
            "photos_count": 1,
            "consolidated_at": now,
        }
        texts = (
            format_consolidation_summary(row),
            format_client_notification(row),
            format_client_consolidation(row),
            format_admin_consolidation(row, full=True),
        )
        for text in texts:
            self.assertIn("CG000001", text)
            self.assertNotIn("<коробка>", text)
            self.assertNotIn("999", text)


class ConsolidationValidationTests(unittest.TestCase):
    def test_missing_cargo_is_rejected(self):
        from repositories.consolidations import CargoNotFoundError, validate_candidates

        pool = FakeConsolidationPool()
        rows = [pool.connection._candidate(pool.connection.cargos[1])]
        with self.assertRaises(CargoNotFoundError):
            validate_candidates(["CG000001", "CG000099"], rows)

    def test_different_clients_are_rejected(self):
        from repositories.consolidations import CargoDifferentClientsError, validate_candidates

        pool = FakeConsolidationPool()
        rows = [pool.connection._candidate(pool.connection.cargos[index]) for index in (1, 3)]
        with self.assertRaises(CargoDifferentClientsError):
            validate_candidates(["CG000001", "CG000003"], rows)

    def test_unavailable_cargo_is_rejected(self):
        from repositories.consolidations import CargoUnavailableError, validate_candidates

        pool = FakeConsolidationPool()
        pool.connection.cargos[2]["status"] = "consolidated"
        rows = [pool.connection._candidate(pool.connection.cargos[index]) for index in (1, 2)]
        with self.assertRaises(CargoUnavailableError):
            validate_candidates(["CG000001", "CG000002"], rows)


class ConsolidationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_finished_cargo_is_rejected_by_new_precheck(self):
        from repositories.consolidations import (
            CargoAlreadyConsolidatedError,
            get_cargos_for_consolidation,
            validate_candidates,
        )

        pool = FakeConsolidationPool()
        await create_test_consolidation(pool)
        rows = await get_cargos_for_consolidation(
            pool, ["CG000001", "CG000002"]
        )
        with self.assertRaises(CargoAlreadyConsolidatedError):
            validate_candidates(["CG000001", "CG000002"], rows)

    async def test_transaction_creates_all_items_photos_and_statuses(self):
        pool = FakeConsolidationPool()
        row = await create_test_consolidation(pool, photos=[photo(1), photo(2)])
        self.assertEqual(row["consolidation_code"], "CS000001")
        self.assertEqual(len(pool.connection.items), 2)
        self.assertEqual(len(pool.connection.photos), 2)
        self.assertEqual(pool.connection.cargos[1]["status"], "consolidated")
        self.assertEqual(pool.connection.cargos[2]["status"], "consolidated")

    async def test_repeated_creation_returns_existing_consolidation(self):
        pool = FakeConsolidationPool()
        first = await create_test_consolidation(pool)
        second = await create_test_consolidation(pool)
        self.assertEqual(first["consolidation_code"], second["consolidation_code"])
        self.assertEqual(len(pool.connection.consolidations), 1)

    async def test_repository_locks_in_stable_order_and_never_uses_max(self):
        from repositories.consolidations import create_consolidation

        source = inspect.getsource(create_consolidation).upper()
        self.assertIn("FOR UPDATE", source)
        self.assertIn("ORDER BY CG.ID", source)
        self.assertNotIn("MAX(", source)

    async def test_item_failure_rolls_back(self):
        pool = FakeConsolidationPool(fail_item=2)
        with self.assertRaises(RuntimeError):
            await create_test_consolidation(pool)
        self.assertEqual(pool.connection.consolidations, {})
        self.assertEqual(pool.connection.items, [])
        self.assertEqual(pool.connection.cargos[1]["status"], "received_china")

    async def test_photo_failure_rolls_back(self):
        pool = FakeConsolidationPool(fail_photo=2)
        with self.assertRaises(RuntimeError):
            await create_test_consolidation(pool, photos=[photo(1), photo(2)])
        self.assertEqual(pool.connection.consolidations, {})
        self.assertEqual(pool.connection.photos, [])
        self.assertEqual(pool.connection.cargos[1]["status"], "received_china")

    async def test_status_failure_rolls_back(self):
        from repositories.consolidations import CargoUnavailableError

        pool = FakeConsolidationPool(fail_update=True)
        with self.assertRaises(CargoUnavailableError):
            await create_test_consolidation(pool)
        self.assertEqual(pool.connection.consolidations, {})
        self.assertEqual(pool.connection.items, [])

    async def test_repository_rejects_invalid_counts(self):
        for codes, photos in ((["CG000001"], [photo(1)]), (["CG000001", "CG000002"], [])):
            with self.subTest(codes=len(codes), photos=len(photos)), self.assertRaises(ValueError):
                await create_test_consolidation(FakeConsolidationPool(), codes, photos)

    async def test_client_owner_and_foreign_access(self):
        from repositories.consolidations import get_client_consolidation_by_code

        pool = FakeConsolidationPool()
        await create_test_consolidation(pool)
        owned = await get_client_consolidation_by_code(pool, 101, "CS000001")
        foreign = await get_client_consolidation_by_code(pool, 202, "CS000001")
        self.assertIsNotNone(owned)
        self.assertIsNone(foreign)

    async def test_lists_search_photos_and_cargo_lookup(self):
        from repositories.consolidations import (
            get_consolidation_by_code,
            get_consolidation_for_cargo,
            get_consolidation_photos,
            list_client_consolidations,
            list_recent_consolidations,
        )

        pool = FakeConsolidationPool()
        row = await create_test_consolidation(pool, photos=[photo(1), photo(2)])
        self.assertEqual(len(await list_client_consolidations(pool, 1)), 1)
        self.assertEqual(len(await list_recent_consolidations(pool)), 1)
        self.assertEqual((await get_consolidation_by_code(pool, "CS000001"))["id"], row["id"])
        self.assertEqual((await get_consolidation_for_cargo(pool, "CG000001"))["id"], row["id"])
        self.assertEqual(len(await get_consolidation_photos(pool, row["id"])), 2)


class ConsolidationIntegrationTests(unittest.TestCase):
    def test_dispatcher_source_includes_consolidation_router(self):
        from bot_app import create_dispatcher

        self.assertIn("include_router(consolidation.router)", inspect.getsource(create_dispatcher))

    def test_migration_order(self):
        from migrations.runner import MIGRATIONS_DIR

        self.assertEqual(
            [path.name for path in sorted(MIGRATIONS_DIR.glob("*.sql"))],
            [
                "001_create_orders.sql",
                "002_create_clients.sql",
                "003_create_china_trackings.sql",
                "004_create_cargos.sql",
                "005_create_consolidations.sql",
                "006_create_shipments.sql",
            ],
        )


if __name__ == "__main__":
    unittest.main()
