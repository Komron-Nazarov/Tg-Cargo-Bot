import unittest
from datetime import datetime, timezone


class AcquireContext:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeTrackingConnection:
    def __init__(self):
        self.rows = {}
        self.next_id = 1
        self.client_details = {
            1: {
                "client_code": "C000001",
                "full_name": "First Client",
                "telegram_user_id": 101,
                "telegram_username": "first",
            },
            2: {
                "client_code": "C000002",
                "full_name": "Second Client",
                "telegram_user_id": 202,
                "telegram_username": None,
            },
        }

    def _admin_row(self, row):
        return {**row, **self.client_details[row["client_id"]]}

    async def fetchrow(self, query, *args):
        compact = " ".join(query.split())
        if "INSERT INTO china_trackings" in compact:
            client_id, tracking_number, normalized = args
            if any(
                row["tracking_number_normalized"] == normalized
                for row in self.rows.values()
            ):
                return None
            now = datetime.now(timezone.utc)
            row = {
                "id": self.next_id,
                "client_id": client_id,
                "tracking_number": tracking_number,
                "tracking_number_normalized": normalized,
                "status": "declared",
                "created_at": now,
                "updated_at": now,
                "cancelled_at": None,
            }
            self.rows[self.next_id] = row
            self.next_id += 1
            return row

        if compact.startswith("UPDATE china_trackings"):
            tracking_id, client_id = args
            row = self.rows.get(tracking_id)
            if (
                row is None
                or row["client_id"] != client_id
                or row["status"] != "declared"
            ):
                return None
            row["status"] = "cancelled"
            row["cancelled_at"] = datetime.now(timezone.utc)
            row["updated_at"] = row["cancelled_at"]
            return row

        if "JOIN clients" in compact:
            normalized = args[0]
            row = next(
                (
                    item
                    for item in self.rows.values()
                    if item["tracking_number_normalized"] == normalized
                ),
                None,
            )
            return self._admin_row(row) if row else None

        if "WHERE tracking_number_normalized = $1" in compact:
            normalized = args[0]
            return next(
                (
                    row
                    for row in self.rows.values()
                    if row["tracking_number_normalized"] == normalized
                ),
                None,
            )

        if "WHERE id = $1 AND client_id = $2" in compact:
            tracking_id, client_id = args
            row = self.rows.get(tracking_id)
            return row if row and row["client_id"] == client_id else None
        raise AssertionError(f"Unexpected fetchrow query: {compact}")

    async def fetch(self, query, *args):
        compact = " ".join(query.split())
        if "WHERE client_id = $1" in compact and "JOIN clients" not in compact:
            client_id, limit = args
            rows = [row for row in self.rows.values() if row["client_id"] == client_id]
            return sorted(rows, key=lambda row: row["id"], reverse=True)[:limit]
        if "WHERE t.status = $1" in compact:
            status, limit = args
            rows = [row for row in self.rows.values() if row["status"] == status]
            return [self._admin_row(row) for row in rows[:limit]]
        if "WHERE c.client_code = $1" in compact:
            client_code, limit = args
            rows = [
                row
                for row in self.rows.values()
                if self.client_details[row["client_id"]]["client_code"] == client_code
            ]
            return [self._admin_row(row) for row in rows[:limit]]
        raise AssertionError(f"Unexpected fetch query: {compact}")


class FakeTrackingPool:
    def __init__(self):
        self.connection = FakeTrackingConnection()

    def acquire(self):
        return AcquireContext(self.connection)


class TrackingServiceTests(unittest.TestCase):
    def test_normalization_uppercases_and_removes_spaces(self):
        from services.tracking_service import normalize_tracking_number

        self.assertEqual(normalize_tracking_number(" lp123456789cn "), "LP123456789CN")
        self.assertEqual(normalize_tracking_number("SF 123 456"), "SF123456")

    def test_minimum_and_maximum_length(self):
        from services.tracking_service import normalize_tracking_number

        self.assertEqual(normalize_tracking_number("A1234"), "A1234")
        self.assertEqual(normalize_tracking_number("A" * 64), "A" * 64)
        for value in ("A123", "A" * 65):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_tracking_number(value)

    def test_cyrillic_url_and_special_characters_are_rejected(self):
        from services.tracking_service import normalize_tracking_number

        for value in (
            "ТРЕК12345",
            "https://example.com/track",
            "LP/12345",
            "LP_12345",
            "LP.12345",
            "-----",
            "",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_tracking_number(value)

    def test_status_label(self):
        from services.tracking_service import status_label

        self.assertIn("Ожидается", status_label("declared"))
        self.assertIn("Отменён", status_label("cancelled"))
        self.assertIn("Принят", status_label("received"))

    def test_client_and_admin_formatters(self):
        from services.tracking_service import (
            format_admin_notification,
            format_admin_tracking,
            format_client_tracking,
        )

        now = datetime(2026, 8, 22, 12, 30, tzinfo=timezone.utc)
        row = {
            "tracking_number": "LP123456789CN",
            "status": "declared",
            "created_at": now,
            "client_code": "C000001",
            "full_name": "First Client",
        }
        self.assertIn("LP123456789CN", format_client_tracking(row))
        self.assertNotIn("id", format_client_tracking(row).lower())
        self.assertIn("C000001", format_admin_tracking(row))

        client = {
            "client_code": "C000001",
            "full_name": "First Client",
            "telegram_user_id": 101,
            "telegram_username": "first",
        }
        notification = format_admin_notification(client, "LP123456789CN")
        self.assertIn("@first", notification)
        self.assertIn("C000001", notification)

    def test_duplicate_messages_do_not_expose_other_client(self):
        from services.tracking_service import duplicate_message

        self.assertIn("вашем списке", duplicate_message(1, 1))
        other = duplicate_message(2, 1)
        self.assertIn("обратитесь к администратору", other)
        self.assertNotIn("C000002", other)


class TrackingRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pool = FakeTrackingPool()

    async def _create(self, client_id=1, number="LP123456789CN"):
        from repositories.trackings import create_tracking

        return await create_tracking(self.pool, client_id, number, number)

    async def test_create_and_find_by_number(self):
        from repositories.trackings import get_tracking_by_normalized

        created = await self._create()
        found = await get_tracking_by_normalized(self.pool, "LP123456789CN")
        self.assertIs(found, created)

    async def test_duplicate_for_same_client_is_not_inserted(self):
        from repositories.trackings import create_tracking
        from services.tracking_service import duplicate_message

        created = await self._create()
        duplicate = await create_tracking(
            self.pool, 1, "LP123456789CN", "LP123456789CN"
        )
        self.assertIsNone(duplicate)
        self.assertIn("вашем списке", duplicate_message(created["client_id"], 1))

    async def test_duplicate_for_other_client_is_not_inserted(self):
        from repositories.trackings import create_tracking
        from services.tracking_service import duplicate_message

        created = await self._create(client_id=1)
        duplicate = await create_tracking(
            self.pool, 2, "LP123456789CN", "LP123456789CN"
        )
        self.assertIsNone(duplicate)
        self.assertIn(
            "обратитесь к администратору",
            duplicate_message(created["client_id"], 2),
        )

    async def test_list_client_trackings(self):
        from repositories.trackings import list_client_trackings

        await self._create(client_id=1, number="FIRST123")
        await self._create(client_id=2, number="SECOND123")
        rows = await list_client_trackings(self.pool, 1)
        self.assertEqual([row["tracking_number"] for row in rows], ["FIRST123"])

    async def test_search_by_client_code_and_number(self):
        from repositories.trackings import (
            search_tracking_by_number,
            search_trackings_by_client_code,
        )

        await self._create(client_id=1)
        by_code = await search_trackings_by_client_code(self.pool, "C000001")
        by_number = await search_tracking_by_number(self.pool, "LP123456789CN")
        self.assertEqual(len(by_code), 1)
        self.assertEqual(by_number["client_code"], "C000001")

    async def test_owner_can_cancel_without_delete(self):
        from repositories.trackings import cancel_client_tracking

        created = await self._create(client_id=1)
        cancelled = await cancel_client_tracking(self.pool, created["id"], 1)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertIn(created["id"], self.pool.connection.rows)

    async def test_other_client_cannot_cancel(self):
        from repositories.trackings import cancel_client_tracking

        created = await self._create(client_id=1)
        self.assertIsNone(
            await cancel_client_tracking(self.pool, created["id"], 2)
        )
        self.assertEqual(created["status"], "declared")

    async def test_cancelled_tracking_cannot_be_cancelled_again(self):
        from repositories.trackings import cancel_client_tracking

        created = await self._create(client_id=1)
        await cancel_client_tracking(self.pool, created["id"], 1)
        self.assertIsNone(
            await cancel_client_tracking(self.pool, created["id"], 1)
        )


if __name__ == "__main__":
    unittest.main()
