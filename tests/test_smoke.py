import importlib
import json
import unittest
from datetime import datetime, timezone


VALID_ENV = {
    "BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
    "ADMIN_ID": "123456",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_NAME": "cargo_bot_test",
    "DB_USER": "test_user",
    "DB_PASSWORD": "test_password",
    "DB_SSL": "disable",
    "DEPLOY_MODE": "polling",
}


def webhook_env():
    return {
        **VALID_ENV,
        "DEPLOY_MODE": "webhook",
        "WEBHOOK_BASE_URL": "https://cargo-bot.onrender.com/",
        "WEBHOOK_PATH": "/telegram/webhook",
        "WEBHOOK_SECRET": "safe_test_secret-123",
        "PORT": "10000",
    }


class ImportSmokeTests(unittest.TestCase):
    def test_application_import_does_not_start_it(self):
        module = importlib.import_module("main")
        self.assertTrue(callable(module.main))


class ConfigurationSmokeTests(unittest.TestCase):
    def test_polling_configuration_does_not_require_webhook_values(self):
        from config import POLLING_MODE, load_settings

        settings = load_settings(VALID_ENV)
        self.assertEqual(settings.deploy_mode, POLLING_MODE)
        self.assertIsNone(settings.webhook_base_url)
        self.assertIsNone(settings.china_warehouse_address)

    def test_optional_warehouse_configuration_is_loaded(self):
        from config import load_settings

        settings = load_settings(
            {
                **VALID_ENV,
                "CHINA_WAREHOUSE_ADDRESS": "Guangzhou test address",
                "CHINA_WAREHOUSE_RECIPIENT": "Cargo Test",
                "CHINA_WAREHOUSE_PHONE": "+861234567890",
            }
        )
        self.assertEqual(settings.china_warehouse_address, "Guangzhou test address")
        self.assertEqual(settings.china_warehouse_recipient, "Cargo Test")
        self.assertEqual(settings.china_warehouse_phone, "+861234567890")

    def test_webhook_configuration_is_accepted(self):
        from config import WEBHOOK_MODE, load_settings

        settings = load_settings(webhook_env())
        self.assertEqual(settings.deploy_mode, WEBHOOK_MODE)
        self.assertEqual(
            settings.webhook_url,
            "https://cargo-bot.onrender.com/telegram/webhook",
        )

    def test_webhook_requires_base_url(self):
        from config import load_settings

        values = webhook_env()
        values.pop("WEBHOOK_BASE_URL")
        with self.assertRaises(RuntimeError):
            load_settings(values)

    def test_webhook_requires_secret(self):
        from config import load_settings

        values = webhook_env()
        values.pop("WEBHOOK_SECRET")
        with self.assertRaises(RuntimeError):
            load_settings(values)

    def test_invalid_deploy_mode_is_rejected(self):
        from config import load_settings

        with self.assertRaises(RuntimeError):
            load_settings({**VALID_ENV, "DEPLOY_MODE": "unknown"})

    def test_invalid_port_is_rejected(self):
        from config import load_settings

        with self.assertRaises(RuntimeError):
            load_settings({**webhook_env(), "PORT": "70000"})

    def test_non_https_webhook_url_is_rejected(self):
        from config import load_settings

        with self.assertRaises(RuntimeError):
            load_settings(
                {**webhook_env(), "WEBHOOK_BASE_URL": "http://example.com"}
            )

    def test_webhook_path_must_start_with_slash(self):
        from config import load_settings

        with self.assertRaises(RuntimeError):
            load_settings({**webhook_env(), "WEBHOOK_PATH": "telegram/webhook"})


class WebhookSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_is_independent_from_database(self):
        from runners.webhook import health

        response = await health(None)
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.text), {"status": "ok"})

    async def test_webhook_application_registers_http_routes(self):
        from config import load_settings
        from runners.webhook import BOT_KEY, create_webhook_app

        app = create_webhook_app(load_settings(webhook_env()))
        paths = {route.resource.canonical for route in app.router.routes()}
        self.assertIn("/health", paths)
        self.assertIn("/telegram/webhook", paths)
        await app[BOT_KEY].session.close()


class FakeConnection:
    def __init__(self):
        self.fetchval_args = None

    async def fetchval(self, query, *args):
        self.fetchval_args = args
        return 42


class AcquireContext:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakePool:
    def __init__(self):
        self.connection = FakeConnection()

    def acquire(self):
        return AcquireContext(self.connection)


class OrdersRepositorySmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_order_uses_pool_and_returns_id(self):
        from repositories.orders import add_order

        pool = FakePool()
        order_id = await add_order(pool, 10, "user", "Box", 2.5, "Tajikistan")

        self.assertEqual(order_id, 42)
        self.assertEqual(
            pool.connection.fetchval_args,
            (10, "user", "Box", 2.5, "Tajikistan"),
        )


class ClientServiceTests(unittest.TestCase):
    def test_phone_is_normalized(self):
        from services.client_service import normalize_phone

        self.assertEqual(normalize_phone("+992 (90) 000-11-22"), "+992900001122")
        self.assertEqual(normalize_phone("00992900001122"), "+992900001122")
        self.assertEqual(normalize_phone("900001122"), "900001122")

    def test_invalid_phone_is_rejected(self):
        from services.client_service import normalize_phone

        for value in ("", "123", "+992-ABC", "+1234567890123456"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_phone(value)

    def test_client_code_is_formatted(self):
        from services.client_service import format_client_code

        self.assertEqual(format_client_code(1), "C000001")
        self.assertEqual(format_client_code(42), "C000042")

    def test_profile_does_not_expose_internal_id(self):
        from services.client_service import format_profile

        text = format_profile(
            {
                "id": 99,
                "client_code": "C000099",
                "full_name": "Test Client",
                "phone": "+992900001122",
                "delivery_city": "Душанбе",
                "created_at": datetime(2026, 8, 22, tzinfo=timezone.utc),
            }
        )
        self.assertIn("C000099", text)
        self.assertIn("Test Client", text)
        self.assertIn("22.08.2026", text)
        self.assertNotIn("database", text.lower())

    def test_warehouse_text_contains_client_code(self):
        from services.client_service import format_warehouse_address

        text = format_warehouse_address(
            "C000007",
            "Guangzhou test address",
            "Cargo Test",
            "+861234567890",
        )
        self.assertIn("C000007", text)
        self.assertIn("Guangzhou test address", text)
        self.assertIn("Cargo Test", text)

    def test_unconfigured_warehouse_has_safe_message(self):
        from services.client_service import format_warehouse_address

        self.assertEqual(
            format_warehouse_address("C000007", None),
            "Адрес склада пока не настроен. Обратитесь к администратору.",
        )


class FakeClientsConnection:
    def __init__(self):
        self.clients = {}
        self.last_args = None

    async def fetchrow(self, query, *args):
        self.last_args = args
        telegram_user_id = args[0]
        if query.lstrip().startswith("SELECT"):
            return self.clients.get(telegram_user_id)

        existing = self.clients.get(telegram_user_id)
        if existing is not None:
            existing["telegram_username"] = args[1]
            return existing

        internal_id = len(self.clients) + 1
        row = {
            "id": internal_id,
            "client_code": f"C{internal_id:06d}",
            "telegram_user_id": telegram_user_id,
            "telegram_username": args[1],
            "full_name": args[2],
            "phone": args[3],
            "delivery_city": args[4],
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        self.clients[telegram_user_id] = row
        return row


class FakeClientsPool:
    def __init__(self):
        self.connection = FakeClientsConnection()

    def acquire(self):
        return AcquireContext(self.connection)


class ClientsRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_repository_creates_and_reads_client(self):
        from repositories.clients import create_client, get_client_by_telegram_id

        pool = FakeClientsPool()
        created = await create_client(
            pool, 100, "client", "Test Client", "+992900001122", "Душанбе"
        )
        loaded = await get_client_by_telegram_id(pool, 100)
        self.assertEqual(created["client_code"], "C000001")
        self.assertIs(loaded, created)

    async def test_repeated_registration_keeps_one_client_id(self):
        from repositories.clients import create_client

        pool = FakeClientsPool()
        first = await create_client(
            pool, 100, "old_name", "Test Client", "+992900001122", "Душанбе"
        )
        second = await create_client(
            pool, 100, "new_name", "Changed Name", "+992933334455", "Худжанд"
        )
        self.assertEqual(len(pool.connection.clients), 1)
        self.assertEqual(first["client_code"], second["client_code"])
        self.assertEqual(second["full_name"], "Test Client")

    async def test_client_insert_is_concurrency_safe_sql(self):
        from repositories.clients import create_client

        pool = FakeClientsPool()
        await create_client(
            pool, 100, "client", "Test Client", "+992900001122", "Душанбе"
        )
        # The repository relies on the database identity and a unique conflict
        # target; it must never allocate IDs via MAX + 1.
        import inspect

        source = inspect.getsource(create_client).upper()
        self.assertIn("ON CONFLICT", source)
        self.assertNotIn("MAX(", source)


if __name__ == "__main__":
    unittest.main()
