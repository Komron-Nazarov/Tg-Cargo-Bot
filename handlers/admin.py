import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from filters import IsAdmin
from keyboards import order_status_kb
from repositories import orders as order_repository
from repositories import trackings as tracking_repository
from services.tracking_service import (
    format_admin_tracking,
    is_client_code,
    normalize_client_code,
    normalize_tracking_number,
)

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.message(Command("trackings"))
async def list_trackings(message: Message, pool):
    try:
        trackings = await tracking_repository.list_declared_trackings(pool, limit=20)
    except Exception:
        logger.exception("Failed to list declared trackings for admin")
        await message.answer("Не удалось загрузить трек-номера. Попробуйте позже.")
        return
    if not trackings:
        await message.answer("Активных китайских трек-номеров нет.")
        return
    await message.answer("📋 <b>Последние активные трек-номера:</b>")
    for tracking in trackings:
        await message.answer(format_admin_tracking(tracking))


@router.message(Command("tracking"))
async def search_tracking(message: Message, command: CommandObject, pool):
    query = (command.args or "").strip()
    if not query:
        await message.answer(
            "Использование:\n"
            "/tracking &lt;трек-номер&gt;\n"
            "/tracking &lt;Client ID&gt;"
        )
        return

    try:
        if is_client_code(query):
            client_code = normalize_client_code(query)
            trackings = await tracking_repository.search_trackings_by_client_code(
                pool, client_code, limit=20
            )
        else:
            normalized = normalize_tracking_number(query)
            tracking = await tracking_repository.search_tracking_by_number(pool, normalized)
            trackings = [tracking] if tracking is not None else []
    except ValueError:
        await message.answer("Некорректный трек-номер или Client ID.")
        return
    except Exception:
        logger.exception("Failed to search trackings for admin")
        await message.answer("Не удалось выполнить поиск. Попробуйте позже.")
        return

    if not trackings:
        await message.answer("Ничего не найдено.")
        return
    for tracking in trackings:
        await message.answer(format_admin_tracking(tracking))


@router.message(Command("orders"))
async def list_orders(message: Message, pool):
    orders = await order_repository.get_orders_by_status(
        pool, status=order_repository.STATUS_NEW, limit=10
    )
    if not orders:
        await message.answer("Новых заявок нет 🎉")
        return

    for order in orders:
        text = (
            f"№{order['id']} от @{order['username'] or order['user_id']}\n"
            f"📦 {order['name']} · {order['weight']} кг → {order['country']}"
        )
        await message.answer(text, reply_markup=order_status_kb(order["id"], order["status"]))


@router.callback_query(F.data.startswith("status:"))
async def change_status(callback: CallbackQuery, bot: Bot, pool):
    _, order_id_str, new_status = callback.data.split(":")
    order_id = int(order_id_str)

    user_id = await order_repository.update_order_status(pool, order_id, new_status)
    if user_id is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    status_label = order_repository.STATUS_LABELS.get(new_status, new_status)
    await callback.message.edit_text(
        callback.message.text + f"\n\nСтатус: {status_label}",
        reply_markup=order_status_kb(order_id, new_status),
    )
    await callback.answer("Статус обновлён")

    try:
        await bot.send_message(user_id, f"📦 Статус твоей заявки №{order_id} изменён: {status_label}")
    except Exception:
        logger.exception(
            "Failed to notify user about order status",
            extra={"order_id": order_id},
        )
