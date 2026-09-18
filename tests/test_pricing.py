import unittest
from decimal import Decimal
from unittest.mock import AsyncMock


class PricingServiceTests(unittest.TestCase):
    def test_comma_and_dot_weights_and_rounding(self):
        from services.pricing_service import estimate_usd, format_estimate, parse_estimate_weight

        self.assertEqual(parse_estimate_weight("2,5"), Decimal("2.5"))
        self.assertEqual(parse_estimate_weight("2.5"), Decimal("2.5"))
        self.assertEqual(estimate_usd(Decimal("2.5"), Decimal("2.8")), Decimal("7.00"))
        self.assertEqual(estimate_usd(Decimal("0.001"), Decimal("2.8")), Decimal("0.00"))
        self.assertIn("$7.00", format_estimate(Decimal("2.5"), Decimal("2.8")))
        self.assertIn("не счёт к оплате", format_estimate(Decimal("2.5"), Decimal("2.8")))

    def test_invalid_weights_are_rejected(self):
        from services.pricing_service import parse_estimate_weight

        for value in ("", "0", "-1", "NaN", "Infinity", "abc", "1,2345", "1000000"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_estimate_weight(value)

    def test_configurable_rate_is_validated(self):
        from config import load_settings
        from tests.test_smoke import VALID_ENV

        self.assertEqual(load_settings(VALID_ENV).price_per_kg_usd, Decimal("2.8"))
        self.assertEqual(
            load_settings({**VALID_ENV, "PRICE_PER_KG_USD": "3.25"}).price_per_kg_usd,
            Decimal("3.25"),
        )
        for value in ("", "0", "-2", "NaN", "Infinity", "abc", "2.12345"):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                load_settings({**VALID_ENV, "PRICE_PER_KG_USD": value})


class PricingHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_command_calculates_without_database(self):
        from config import load_settings
        from handlers.calculator import calculate_command
        from tests.test_smoke import VALID_ENV

        message = AsyncMock()
        command = type("Command", (), {"args": "2.5"})()
        state = AsyncMock()
        await calculate_command(message, command, state, load_settings(VALID_ENV))
        self.assertIn("$7.00", message.answer.await_args.args[0])
        state.clear.assert_awaited_once()

    async def test_welcome_calculator_needs_no_registration(self):
        from handlers.calculator import calculate_from_welcome
        from states import PriceCalculatorForm

        callback = AsyncMock()
        state = AsyncMock()
        await calculate_from_welcome(callback, state)
        state.set_state.assert_awaited_with(PriceCalculatorForm.weight)
        callback.message.answer.assert_awaited_once()
        callback.answer.assert_awaited_once()

    async def test_button_prompts_then_clears_state_after_calculation(self):
        from config import load_settings
        from handlers.calculator import calculate_button, calculate_weight
        from states import PriceCalculatorForm
        from tests.test_smoke import VALID_ENV

        message = AsyncMock()
        state = AsyncMock()
        await calculate_button(message, state)
        state.set_state.assert_awaited_with(PriceCalculatorForm.weight)
        message.text = "2,5"
        await calculate_weight(message, state, load_settings(VALID_ENV))
        self.assertIn("$7.00", message.answer.await_args.args[0])
        self.assertEqual(state.clear.await_count, 2)

    async def test_invalid_weight_keeps_calculator_open(self):
        from config import load_settings
        from handlers.calculator import calculate_weight
        from tests.test_smoke import VALID_ENV

        message = AsyncMock()
        message.text = "abc"
        state = AsyncMock()
        await calculate_weight(message, state, load_settings(VALID_ENV))
        state.clear.assert_not_awaited()
        self.assertIn("Введите вес", message.answer.await_args.args[0])

    async def test_cancel_does_not_need_database(self):
        from handlers.client import cmd_cancel
        from states import PriceCalculatorForm

        message = AsyncMock()
        state = AsyncMock()
        state.get_state.return_value = PriceCalculatorForm.weight.state
        await cmd_cancel(message, state, object())
        state.clear.assert_awaited_once()
        self.assertIn("Расчёт отменён", message.answer.await_args.args[0])
