import unittest


class GuideTests(unittest.TestCase):
    def test_walkthrough_covers_full_delivery(self):
        from services.guide_service import ADMIN_GUIDE, CLIENT_GUIDE, guide_page

        self.assertEqual(len(CLIENT_GUIDE), 4)
        self.assertEqual(len(ADMIN_GUIDE), 4)
        text = " ".join(CLIENT_GUIDE)
        for term in ("Client ID", "трек-номера", "Cargo ID", "фотографии", "таможни", "оплату"):
            self.assertIn(term, text)
        self.assertIn("Страница 1/4", guide_page("admin", 0))
        with self.assertRaises(ValueError):
            guide_page("client", 4)

    def test_buttons_and_commands_are_registered(self):
        from pathlib import Path
        from keyboards import MAIN_MENU_BUTTONS, guide_kb, registration_prompt_kb

        source = (Path(__file__).resolve().parents[1] / "bot_app.py").read_text(encoding="utf-8")
        self.assertIn("dispatcher.include_router(guide.router)", source)
        self.assertIn("📖 Как пользоваться", MAIN_MENU_BUTTONS)
        self.assertEqual(guide_kb("client", 0).inline_keyboard[0][0].callback_data, "guide:client:1")
        self.assertEqual(registration_prompt_kb().inline_keyboard[1][0].callback_data, "guide:client:0")


class OrderValidationTests(unittest.TestCase):
    def test_untrusted_html_and_invalid_numbers(self):
        from html import escape
        from services.order_service import normalize_order_country, normalize_order_name, parse_order_weight

        self.assertEqual(escape(normalize_order_name("  <b> test  ")), "&lt;b&gt; test")
        self.assertEqual(normalize_order_country("  Таджикистан "), "Таджикистан")
        self.assertEqual(parse_order_weight("2,5"), 2.5)
        for value in ("nan", "inf", "-inf", "0", "-2", "1000000", "oops"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_order_weight(value)


class ClientSortingTests(unittest.IsolatedAsyncioTestCase):
    def test_page_validation(self):
        from services.client_service import parse_page

        self.assertEqual(parse_page("2"), 2)
        for value in ("0", "-1", "1.5", "10000", "１２"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_page(value)

    async def test_queries_use_code_and_stable_order(self):
        from repositories.clients import get_client_by_code, list_recent_clients
        from repositories.cargos import list_cargos_by_client_code
        from tests.test_smoke import AcquireContext

        class Connection:
            async def fetchrow(self, sql, *args):
                self.row_sql, self.row_args = sql, args
                return None

            async def fetch(self, sql, *args):
                self.list_sql, self.list_args = sql, args
                return []

        class Pool:
            def __init__(self):
                self.conn = Connection()

            def acquire(self):
                return AcquireContext(self.conn)

        pool = Pool()
        await get_client_by_code(pool, "C000007")
        self.assertIn("WHERE client_code = $1", pool.conn.row_sql)
        self.assertEqual(pool.conn.row_args, ("C000007",))
        await list_recent_clients(pool)
        self.assertIn("ORDER BY id DESC", pool.conn.list_sql)
        await list_cargos_by_client_code(pool, "C000007")
        self.assertIn("WHERE c.client_code = $1", pool.conn.list_sql)
        self.assertIn("ORDER BY cg.received_at DESC, cg.id DESC", pool.conn.list_sql)
        self.assertEqual(pool.conn.list_args, ("C000007", 20, 0))
