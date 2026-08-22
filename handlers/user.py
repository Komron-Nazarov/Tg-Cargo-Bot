import logging

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Settings
from handlers.client import require_registered_client
from keyboards import confirm_kb, countries_kb, main_menu_kb, order_status_kb
from repositories import orders as order_repository
from states import OrderForm

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text == "📦 Новая заявка")
async def new_order(message: Message, state: FSMContext, pool):
    if await require_registered_client(message, state, pool) is None:
        return
    await state.set_state(OrderForm.name)
    await message.answer(
        "📦 Введи имя груза (например: «Коробка с одеждой»):\n\n"
        "В любой момент можно отменить: /cancel"
    )


@router.message(F.text == "📋 Мои заявки")
async def my_orders(message: Message, state: FSMContext, pool):
    if await require_registered_client(message, state, pool) is None:
        return
    orders = await order_repository.get_user_orders(pool, message.from_user.id)
    if not orders:
        await message.answer("У тебя пока нет заявок. Нажми «📦 Новая заявка», чтобы создать первую.")
        return

    lines = ["📋 Твои заявки:\n"]
    for order in orders:
        status_label = order_repository.STATUS_LABELS.get(order["status"], order["status"])
        lines.append(
            f"№{order['id']} · {order['name']} · {order['weight']} кг · {order['country']} — {status_label}"
        )
    await message.answer("\n".join(lines))


# --- шаги формы (FSM) ---

@router.message(StateFilter(OrderForm.name))
async def process_name(message: Message, state: FSMContext):
    if not message.text or len(message.text) < 2:
        await message.answer("❌ Название слишком короткое. Введи ещё раз:")
        return
    await state.update_data(name=message.text)
    await state.set_state(OrderForm.weight)
    await message.answer("⚖️ Теперь введи вес груза в кг (например: 2.5):")


@router.message(StateFilter(OrderForm.weight))
async def process_weight(message: Message, state: FSMContext):
    try:
        weight = float((message.text or "").replace(",", "."))
        if weight <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число больше нуля, например 2.5")
        return

    await state.update_data(weight=weight)
    await state.set_state(OrderForm.country)
    await message.answer("🌍 Куда доставляем? Выбери страну или введи вручную:", reply_markup=countries_kb())


@router.callback_query(StateFilter(OrderForm.country), F.data.startswith("country:"))
async def process_country_button(callback: CallbackQuery, state: FSMContext):
    country = callback.data.split(":", 1)[1]
    if country == "other":
        await callback.message.edit_text("✏️ Введи страну текстом:")
        await callback.answer()
        return

    await state.update_data(country=country)
    await show_confirmation(callback.message, state)
    await callback.answer()


@router.message(StateFilter(OrderForm.country))
async def process_country_text(message: Message, state: FSMContext):
    await state.update_data(country=message.text)
    await show_confirmation(message, state)


async def show_confirmation(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(OrderForm.confirm)
    text = (
        "Проверь заявку:\n\n"
        f"📦 Груз: {data['name']}\n"
        f"⚖️ Вес: {data['weight']} кг\n"
        f"🌍 Страна: {data['country']}\n\n"
        "Всё верно?"
    )
    await message.answer(text, reply_markup=confirm_kb())


@router.callback_query(StateFilter(OrderForm.confirm), F.data.startswith("confirm:"))
async def process_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    pool,
    settings: Settings,
):
    action = callback.data.split(":", 1)[1]

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Заявка отменена.")
        await callback.answer()
        return

    if action == "restart":
        await state.set_state(OrderForm.name)
        await callback.message.edit_text("📦 Введи имя груза заново:")
        await callback.answer()
        return

    data = await state.get_data()
    order_id = await order_repository.add_order(
        pool,
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        name=data["name"],
        weight=data["weight"],
        country=data["country"],
    )
    await state.clear()
    await callback.message.edit_text(f"✅ Заявка №{order_id} создана! Мы свяжемся с тобой по деталям доставки.")
    await callback.answer()

    if callback.from_user.id != settings.admin_id:
        try:
            await bot.send_message(
                settings.admin_id,
                f"🧠 Новая заявка №{order_id}\n"
                f"От: @{callback.from_user.username or callback.from_user.id}\n"
                f"📦 {data['name']}, {data['weight']} кг → {data['country']}",
                reply_markup=order_status_kb(order_id, "new"),
            )
        except Exception:
            logger.exception(
                "Failed to notify admin about a new order",
                extra={"order_id": order_id},
            )


# --- заглушка для всего, что не попало ни в одно состояние ---

@router.message(StateFilter(None))
async def fallback(message: Message):
    await message.answer(
        "Не совсем понял 🙂 Используй кнопки меню или /start, чтобы начать.",
        reply_markup=main_menu_kb(),
    )
