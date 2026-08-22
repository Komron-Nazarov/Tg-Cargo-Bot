import importlib
import json
import unittest


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


if __name__ == "__main__":
    unittest.main()
