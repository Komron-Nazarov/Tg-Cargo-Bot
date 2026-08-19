import importlib
import os
import unittest
from unittest.mock import patch


VALID_ENV = {
    "BOT_TOKEN": "test-token",
    "ADMIN_ID": "123456",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_NAME": "cargo_bot_test",
    "DB_USER": "test_user",
    "DB_PASSWORD": "test_password",
    "DB_SSL": "disable",
}


class ImportSmokeTests(unittest.TestCase):
    def test_application_imports(self):
        with patch.dict(os.environ, VALID_ENV, clear=True):
            module = importlib.import_module("main")
        self.assertTrue(callable(module.main))


class ConfigurationSmokeTests(unittest.TestCase):
    def test_valid_configuration(self):
        from config import load_settings

        settings = load_settings(VALID_ENV)
        self.assertEqual(settings.admin_id, 123456)
        self.assertEqual(settings.db_port, 5432)

    def test_invalid_port_is_rejected(self):
        from config import load_settings

        invalid = {**VALID_ENV, "DB_PORT": "70000"}
        with self.assertRaises(RuntimeError):
            load_settings(invalid)


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


if __name__ == "__main__":
    unittest.main()
