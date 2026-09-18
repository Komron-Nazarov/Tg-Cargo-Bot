import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from filters import IsAdmin
from keyboards import order_status_kb
from repositories import orders as order_repository
from repositories import clients as client_repository
from repositories import cargos as cargo_repository
from repositories import trackings as tracking_repository
from services.tracking_service import (
    format_admin_tracking,
    is_client_code,
    normalize_client_code,
    normalize_tracking_number,
)
from services.cargo_service import format_admin_cargo
from services.client_service import parse_page
from services.admin_overview_service import format_admin_order, format_client_overview

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.message(Command("clients"))
async def list_clients(message: Message, command: CommandObject, pool):
    try:
        page = parse_page(command.args or "1")
    except ValueError:
        await message.answer("Использование: /clients [номер страницы]")
        return
    try:
        clients = await client_repository.list_recent_clients(pool, limit=20, offset=(page - 1) * 20)
    except Exception:
        logger.exception("Failed to list clients")
        await message.answer("Не удалось загрузить клиентов. Попробуйте позже.")
        return
    if not clients:
        await message.answer("Клиентов на этой странице нет.")
        return
    lines = [f"👥 <b>Клиенты · страница {page}</b>"]
    for client in clients:
        lines.append(
            f"<code>{escape(str(client['client_code']))}</code> · "
            f"{escape(str(client['full_name']))} · {escape(str(client['delivery_city']))}"
        )
    lines.append("Поиск: /client_search имя или телефон · карточка: /client C000001")
    if len(clients) == 20 and page < 9999:
        lines.append(f"Далее: /clients {page + 1}")
    await message.answer("\n".join(lines))


@router.message(Command("client_search"))
async def search_clients(message: Message, command: CommandObject, pool):
    query = (command.args or "").strip()
    if len(query) < 2 or len(query) > 100:
        await message.answer("Использование: /client_search &lt;имя, телефон или Client ID&gt; (2–100 символов)")
        return
    try:
        clients = await client_repository.search_clients(pool, query, limit=20)
    except Exception:
        logger.exception("Failed to search clients")
        await message.answer("Не удалось найти клиентов. Попробуйте позже.")
        return
    if not clients:
        await message.answer("Клиенты не найдены.")
        return
    lines = ["🔍 <b>Найденные клиенты (до 20):</b>"]
    for client in clients:
        code = escape(str(client["client_code"]))
        lines.append(
            f"<code>{code}</code> · {escape(str(client['full_name']))} · "
            f"{escape(str(client['phone']))} · /client {code}"
        )
    await message.answer("\n".join(lines))


@router.message(Command("client"))
async def find_client(message: Message, command: CommandObject, pool):
    try:
        code = normalize_client_code(command.args or "")
    except ValueError:
        await message.answer("Использование: /client &lt;Client ID&gt;")
        return
    try:
        client = await client_repository.get_client_by_code(pool, code)
        if client is not None:
            trackings = await tracking_repository.search_trackings_by_client_code(
                pool, code, limit=5
            )
            cargos = await cargo_repository.list_cargos_by_client_code(
                pool, code, limit=5, offset=0
            )
            orders = await order_repository.get_recent_user_orders(
                pool, client["telegram_user_id"], limit=5
            )
    except Exception:
        logger.exception("Failed to load client by code")
        await message.answer("Не удалось загрузить клиента. Попробуйте позже.")
        return
    if client is None:
        await message.answer("Client ID не найден. Не назначайте груз наугад.")
        return
    await message.answer(format_client_overview(client, trackings, cargos, orders))


@router.message(Command("client_cargos"))
async def find_client_cargos(message: Message, command: CommandObject, pool):
    try:
        parts = (command.args or "").split()
        if not 1 <= len(parts) <= 2:
            raise ValueError
        code = normalize_client_code(parts[0])
        page = parse_page(parts[1]) if len(parts) == 2 else 1
    except ValueError:
        await message.answer("Использование: /client_cargos &lt;Client ID&gt; [страница]")
        return
    try:
        client = await client_repository.get_client_by_code(pool, code)
        if client is None:
            await message.answer("Client ID не найден.")
            return
        cargos = await cargo_repository.list_cargos_by_client_code(
            pool, code, limit=20, offset=(page - 1) * 20
        )
    except Exception:
        logger.exception("Failed to list cargos by client")
        await message.answer("Не удалось загрузить грузы клиента. Попробуйте позже.")
        return
    if not cargos:
        await message.answer(f"У клиента <code>{escape(code)}</code> нет грузов на странице {page}.")
        return
    await message.answer(f"📦 <b>Грузы клиента <code>{escape(code)}</code> · страница {page}:</b>")
    for cargo in cargos:
        await message.answer(format_admin_cargo(cargo, full=True))
    if len(cargos) == 20 and page < 9999:
        await message.answer(f"Далее: /client_cargos {escape(code)} {page + 1}")


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
    try:
        orders = await order_repository.get_orders_by_status(
            pool, status=order_repository.STATUS_NEW, limit=10
        )
    except Exception:
        logger.exception("Failed to load new requests")
        await message.answer("Не удалось загрузить запросы. Попробуйте позже.")
        return
    if not orders:
        await message.answer("Новых запросов нет 🎉")
        return

    for order in orders:
        await message.answer(
            format_admin_order(order),
            reply_markup=order_status_kb(order["id"], order["status"]),
        )


@router.message(Command("order"))
async def find_order(message: Message, command: CommandObject, pool):
    raw_id = (command.args or "").strip()
    if not raw_id.isascii() or not raw_id.isdecimal() or not 1 <= len(raw_id) <= 10:
        await message.answer("Использование: /order &lt;номер запроса&gt;")
        return
    order_id = int(raw_id)
    if order_id <= 0:
        await message.answer("Использование: /order &lt;номер запроса&gt;")
        return
    try:
        order = await order_repository.get_order_for_admin(pool, order_id)
    except Exception:
        logger.exception("Failed to load request by ID", extra={"order_id": order_id})
        await message.answer("Не удалось загрузить запрос. Попробуйте позже.")
        return
    if order is None:
        await message.answer("Запрос не найден.")
        return
    await message.answer(
        format_admin_order(order),
        reply_markup=order_status_kb(order["id"], order["status"]),
    )


@router.callback_query(F.data.startswith("status:"))
async def change_status(callback: CallbackQuery, bot: Bot, pool):
    try:
        _, order_id_str, new_status = callback.data.split(":")
        order_id = int(order_id_str)
        if order_id <= 0 or new_status not in {
            order_repository.STATUS_IN_PROGRESS, order_repository.STATUS_DONE
        }:
            raise ValueError
    except (ValueError, AttributeError):
        await callback.answer("Некорректное действие.", show_alert=True)
        return

    try:
        user_id = await order_repository.update_order_status(pool, order_id, new_status)
    except Exception:
        logger.exception("Failed to update request status", extra={"order_id": order_id})
        await callback.answer("Не удалось изменить статус.", show_alert=True)
        return
    if user_id is None:
        await callback.answer("Запрос не найден", show_alert=True)
        return

    status_label = order_repository.STATUS_LABELS.get(new_status, new_status)
    await callback.message.edit_text(
        escape(callback.message.text or "") + f"\n\nСтатус: {escape(status_label)}",
        reply_markup=order_status_kb(order_id, new_status),
    )
    await callback.answer("Статус обновлён")

    try:
        await bot.send_message(user_id, f"📦 Статус твоего запроса №{order_id} изменён: {status_label}")
    except Exception:
        logger.exception(
            "Failed to notify user about order status",
            extra={"order_id": order_id},
        )
