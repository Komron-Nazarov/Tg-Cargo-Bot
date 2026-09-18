import unittest
from unittest.mock import AsyncMock, patch


class AdminOverviewTests(unittest.TestCase):
    def test_client_overview_contains_identity_and_recent_records(self):
        from services.admin_overview_service import format_client_overview

        client = {
            "client_code": "C000001", "full_name": "<Ali>", "phone": "+992123456789",
            "delivery_city": "Душанбе", "telegram_username": None,
            "telegram_user_id": 123, "is_active": True,
        }
        result = format_client_overview(
            client,
            [{"tracking_number": "LP123CN", "status": "declared"}],
            [{"cargo_code": "CG000001", "status": "received"}],
            [{"id": 7, "name": "<товар>", "status": "new"}],
        )
        for value in ("C000001", "LP123CN", "CG000001", "№7", "+992123456789"):
            self.assertIn(value, result)
        self.assertIn("&lt;Ali&gt;", result)
        self.assertIn("&lt;товар&gt;", result)
        self.assertNotIn("<Ali>", result)

    def test_order_card_shows_linked_client_and_escapes_text(self):
        from services.admin_overview_service import format_admin_order

        result = format_admin_order({
            "id": 7, "user_id": 123, "username": None, "name": "<товар>",
            "weight": 2.5, "country": "Китай", "status": "new",
            "client_code": "C000001", "full_name": "<Ali>",
            "phone": "+992123456789", "delivery_city": "Душанбе",
        })
        self.assertIn("/client C000001", result)
        self.assertIn("&lt;товар&gt;", result)
        self.assertIn("&lt;Ali&gt;", result)


class AdminRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_escapes_wildcards_and_uses_parameters(self):
        from repositories.clients import search_clients
        from tests.test_smoke import AcquireContext

        class Connection:
            async def fetch(self, sql, *args):
                self.sql, self.args = sql, args
                return []

        class Pool:
            def __init__(self):
                self.conn = Connection()

            def acquire(self):
                return AcquireContext(self.conn)

        pool = Pool()
        await search_clients(pool, "A_%")
        self.assertIn("ILIKE $1", pool.conn.sql)
        self.assertEqual(pool.conn.args, ("%A!_!%%", 20))

    async def test_client_command_loads_linked_records(self):
        from handlers.admin import find_client

        client = {
            "client_code": "C000001", "full_name": "Ali", "phone": "1234567",
            "delivery_city": "Душанбе", "telegram_username": None,
            "telegram_user_id": 123, "is_active": True,
        }
        message = AsyncMock()
        command = type("Command", (), {"args": "C000001"})()
        with (
            patch("handlers.admin.client_repository.get_client_by_code", new=AsyncMock(return_value=client)),
            patch("handlers.admin.tracking_repository.search_trackings_by_client_code", new=AsyncMock(return_value=[])),
            patch("handlers.admin.cargo_repository.list_cargos_by_client_code", new=AsyncMock(return_value=[])),
            patch("handlers.admin.order_repository.get_recent_user_orders", new=AsyncMock(return_value=[])),
        ):
            await find_client(message, command, object())
        self.assertIn("C000001", message.answer.await_args.args[0])
        self.assertIn("Последние запросы", message.answer.await_args.args[0])

    async def test_order_command_loads_any_status_by_id(self):
        from handlers.admin import find_order

        row = {
            "id": 7, "user_id": 123, "username": None, "name": "Товар",
            "weight": 2.5, "country": "Китай", "status": "done",
            "client_code": None,
        }
        message = AsyncMock()
        command = type("Command", (), {"args": "7"})()
        with patch("handlers.admin.order_repository.get_order_for_admin", new=AsyncMock(return_value=row)):
            await find_order(message, command, object())
        self.assertIn("Запрос №7", message.answer.await_args.args[0])
