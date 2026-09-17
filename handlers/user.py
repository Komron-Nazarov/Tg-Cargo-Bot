import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Settings
from handlers.client import require_registered_client
from keyboards import confirm_kb, countries_kb, main_menu_kb, order_status_kb
from repositories import orders as order_repository
from states import OrderForm
from services.order_service import normalize_order_country, normalize_order_name, parse_order_weight

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text.in_({"📦 Новый запрос", "📦 Новая заявка"}))
async def new_order(message: Message, state: FSMContext, pool):
    if await require_registered_client(message, state, pool) is None:
        return
    await state.set_state(OrderForm.name)
    await message.answer(
        "📦 Введи имя груза (например: «Коробка с одеждой»):\n\n"
        "В любой момент можно отменить: /cancel"
    )


@router.message(F.text.in_({"📋 Мои запросы", "📋 Мои заявки"}))
async def my_orders(message: Message, state: FSMContext, pool):
    if await require_registered_client(message, state, pool) is None:
        return
    try:
        orders = await order_repository.get_user_orders(pool, message.from_user.id)
    except Exception:
        logger.exception("Failed to load client requests")
        await message.answer("Не удалось загрузить запросы. Попробуйте позже.")
        return
    if not orders:
        await message.answer("У тебя пока нет запросов. Нажми «📦 Новый запрос», чтобы создать первый.")
        return

    lines = ["📋 Твои запросы:\n"]
    for order in orders:
        status_label = order_repository.STATUS_LABELS.get(order["status"], order["status"])
        lines.append(
            f"№{order['id']} · {escape(str(order['name']))} · {order['weight']} кг · "
            f"{escape(str(order['country']))} — {escape(str(status_label))}"
        )
    await message.answer("\n".join(lines))


# --- шаги формы (FSM) ---

@router.message(StateFilter(OrderForm.name))
async def process_name(message: Message, state: FSMContext):
    try:
        name = normalize_order_name(message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ {escape(str(exc))}. Введи ещё раз:")
        return
    await state.update_data(name=name)
    await state.set_state(OrderForm.weight)
    await message.answer("⚖️ Теперь введи вес груза в кг (например: 2.5):")


@router.message(StateFilter(OrderForm.weight))
async def process_weight(message: Message, state: FSMContext):
    try:
        weight = parse_order_weight(message.text or "")
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

    try:
        country = normalize_order_country(country)
    except ValueError:
        await callback.answer("Некорректная страна.", show_alert=True)
        return
    await state.update_data(country=country)
    await show_confirmation(callback.message, state)
    await callback.answer()


@router.message(StateFilter(OrderForm.country))
async def process_country_text(message: Message, state: FSMContext):
    try:
        country = normalize_order_country(message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ {escape(str(exc))}. Введите страну ещё раз:")
        return
    await state.update_data(country=country)
    await show_confirmation(message, state)


async def show_confirmation(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(OrderForm.confirm)
    text = (
        "Проверь запрос:\n\n"
        f"📦 Груз: {escape(data['name'])}\n"
        f"⚖️ Вес: {data['weight']} кг\n"
        f"🌍 Страна: {escape(data['country'])}\n\n"
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
    if action not in {"cancel", "restart", "yes"}:
        await callback.answer("Некорректное действие.", show_alert=True)
        return

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Запрос отменён.")
        await callback.answer()
        return

    if action == "restart":
        await state.set_state(OrderForm.name)
        await callback.message.edit_text("📦 Введи имя груза заново:")
        await callback.answer()
        return

    data = await state.get_data()
    try:
        order_id = await order_repository.add_order(
            pool,
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            name=data["name"],
            weight=data["weight"],
            country=data["country"],
        )
    except Exception:
        logger.exception("Failed to save client request")
        await callback.answer("Не удалось сохранить запрос. Попробуйте позже.", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(f"✅ Запрос №{order_id} создан! Мы свяжемся с тобой по деталям доставки.")
    await callback.answer()

    if callback.from_user.id != settings.admin_id:
        try:
            await bot.send_message(
                settings.admin_id,
                f"🧠 Новый запрос №{order_id}\n"
                f"От: @{escape(str(callback.from_user.username or callback.from_user.id))}\n"
                f"📦 {escape(data['name'])}, {data['weight']} кг → {escape(data['country'])}",
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
