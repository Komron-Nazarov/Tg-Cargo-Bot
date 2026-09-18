import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from config import load_settings
from services.demo_service import LAST_STEP, DemoState, demo_actions, demo_card
from tests.test_smoke import VALID_ENV


class DemoServiceTests(unittest.TestCase):
    def test_full_journey_has_only_demo_identifiers_and_no_database_dependency(self):
        state = DemoState()
        choices = {0: "s", 1: "b", 7: "y", 11: "h"}
        all_cards = []
        for step in range(LAST_STEP + 1):
            self.assertEqual(state.step, step)
            card = demo_card(state, Decimal("2.8"))
            all_cards.append(card)
            self.assertIn("ДЕМО", card)
            self.assertIn(f"шаг {step + 1}/{LAST_STEP + 1}", card)
            actions = demo_actions(state)
            self.assertTrue(actions)
            if step < LAST_STEP:
                selected = choices.get(step)
                encoded = next(
                    payload for _label, payload in actions
                    if selected is None or payload.split(":")[step_choice_index(step)] == selected
                )
                state = DemoState.decode(encoded)
        self.assertIn("DEMO-", " ".join(all_cards))
        self.assertIn("$7.00", demo_card(state, Decimal("2.8")))
        self.assertEqual(demo_actions(state)[0][1], DemoState().encode())

    def test_rejects_invalid_or_incomplete_callbacks(self):
        for value in (
            "demo:exit", "demo:-1:-:-:-:-", "demo:15:s:b:y:h",
            "demo:2:s:-:-:-", "demo:8:s:b:-:-", "demo:12:s:b:y:-",
            "demo:2:<tag>:b:-:-", "demo:2:s:b:-:-:extra",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                DemoState.decode(value)

    def test_choice_is_reflected_and_price_uses_current_rate(self):
        state = DemoState(step=14, product="c", weight="c", consolidated="n", city="d")
        card = demo_card(state, Decimal("3.25"))
        self.assertIn("$16.25", card)
        self.assertIn("TJS", card)
        self.assertIn("не создано", card)


def step_choice_index(step: int) -> int:
    return {0: 2, 1: 3, 7: 4, 11: 5}[step]


class DemoHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_offers_training_without_database_access(self):
        from handlers.client import cmd_start

        message = SimpleNamespace(answer=AsyncMock())
        state = SimpleNamespace(clear=AsyncMock())
        await cmd_start(message, state, pool=None)
        state.clear.assert_awaited_once()
        self.assertIn("учебный заказ", message.answer.call_args.args[0])
        buttons = message.answer.call_args.kwargs["reply_markup"].inline_keyboard
        self.assertEqual(buttons[0][0].callback_data, "demo:start")
        self.assertEqual(buttons[1][0].callback_data, "demo:skip")

    async def test_skip_shows_registration_and_existing_client_shows_menu(self):
        from handlers.demo import demo_exit

        message = SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock())
        callback = SimpleNamespace(message=message, from_user=SimpleNamespace(id=123), answer=AsyncMock())
        state = SimpleNamespace(clear=AsyncMock())
        with patch("handlers.demo.get_registered_client", new=AsyncMock(return_value=None)):
            await demo_exit(callback, state, pool=object())
        self.assertIn("Зарегистрироваться", str(message.answer.call_args.kwargs["reply_markup"].inline_keyboard))
        with patch("handlers.demo.get_registered_client", new=AsyncMock(return_value={"id": 1})):
            await demo_exit(callback, state, pool=object())
        self.assertIn("Основное меню", message.answer.call_args.args[0])

    async def test_demo_can_be_restarted_without_database(self):
        from handlers.demo import demo_command

        message = SimpleNamespace(answer=AsyncMock())
        state = SimpleNamespace(clear=AsyncMock())
        await demo_command(message, state, load_settings(VALID_ENV))
        self.assertIn("шаг 1/15", message.answer.call_args.args[0])
        state.clear.assert_awaited_once()
