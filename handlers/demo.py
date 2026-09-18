import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Settings
from handlers.client import get_registered_client
from keyboards import demo_step_kb, main_menu_kb, registration_prompt_kb
from services.demo_service import DemoState, demo_card

router = Router()
logger = logging.getLogger(__name__)


async def _show_real_bot(message: Message, user_id: int, pool) -> None:
    try:
        client = await get_registered_client(pool, user_id)
    except Exception:
        logger.exception("Failed to load client after demo")
        await message.answer("Не удалось открыть основное меню. Попробуйте /start позже.")
        return
    if client is None:
        await message.answer(
            "Для реальной работы зарегистрируйтесь. Обучение можно повторить командой /demo:",
            reply_markup=registration_prompt_kb(),
        )
    else:
        await message.answer("Основное меню готово. Обучение можно повторить командой /demo.", reply_markup=main_menu_kb())


@router.message(Command("demo"))
@router.message(F.text == "🎓 Учебный заказ")
async def demo_command(message: Message, state: FSMContext, settings: Settings):
    await state.clear()
    first = DemoState()
    await message.answer(demo_card(first, settings.price_per_kg_usd), reply_markup=demo_step_kb(first))


@router.callback_query(F.data == "demo:start")
async def demo_start(callback: CallbackQuery, state: FSMContext, settings: Settings):
    await state.clear()
    first = DemoState()
    await callback.message.edit_text(
        demo_card(first, settings.price_per_kg_usd), reply_markup=demo_step_kb(first)
    )
    await callback.answer()


@router.callback_query(F.data.in_({"demo:skip", "demo:exit"}))
async def demo_exit(callback: CallbackQuery, state: FSMContext, pool):
    await state.clear()
    await callback.message.edit_text("🎓 Обучение закрыто. Никаких реальных записей не создано.")
    await callback.answer()
    await _show_real_bot(callback.message, callback.from_user.id, pool)


@router.callback_query(F.data.startswith("demo:"))
async def demo_step(callback: CallbackQuery, settings: Settings):
    try:
        current = DemoState.decode(callback.data or "")
    except ValueError:
        await callback.answer("Учебный шаг недоступен. Начните заново: /demo", show_alert=True)
        return
    await callback.message.edit_text(
        demo_card(current, settings.price_per_kg_usd),
        reply_markup=demo_step_kb(current),
    )
    await callback.answer()
