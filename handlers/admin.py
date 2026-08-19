import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from filters import IsAdmin
from keyboards import order_status_kb
from repositories import orders as order_repository

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


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
