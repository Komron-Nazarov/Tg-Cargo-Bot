import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Settings
from handlers.client import (
    begin_registration,
    get_registered_client,
    require_registered_client,
)
from keyboards import (
    tracking_cancel_confirm_kb,
    tracking_cancel_kb,
    tracking_confirm_kb,
    tracking_menu_kb,
)
from repositories import trackings as tracking_repository
from services.tracking_service import (
    STATUS_DECLARED,
    duplicate_message,
    format_admin_notification,
    format_client_tracking,
    normalize_tracking_number,
)
from states import TrackingForm

router = Router()
logger = logging.getLogger(__name__)


async def require_callback_client(callback: CallbackQuery, state: FSMContext, pool):
    try:
        client = await get_registered_client(pool, callback.from_user.id)
    except Exception:
        logger.exception("Failed to load client for tracking callback")
        await callback.answer("Не удалось загрузить профиль. Попробуйте позже.", show_alert=True)
        return None
    if client is not None:
        return client
    await callback.message.answer("Сначала нужно зарегистрироваться в Cargo Bot.")
    await begin_registration(callback.message, state)
    await callback.answer()
    return None


@router.message(StateFilter(None), F.text == "🔎 Китайские трек-номера")
async def tracking_section(message: Message, state: FSMContext, pool):
    try:
        client = await require_registered_client(message, state, pool)
    except Exception:
        logger.exception("Failed to open tracking section")
        await message.answer("Не удалось загрузить профиль. Попробуйте позже.")
        return
    if client is None:
        return
    await message.answer(
        "🔎 <b>Китайские трек-номера</b>\n\nВыберите действие:",
        reply_markup=tracking_menu_kb(),
    )


@router.callback_query(F.data == "tracking:add")
async def tracking_add_start(callback: CallbackQuery, state: FSMContext, pool):
    if await require_callback_client(callback, state, pool) is None:
        return
    await state.clear()
    await state.set_state(TrackingForm.number)
    await callback.message.answer(
        "Введите Chinese Tracking Number.\n\n"
        "Разрешены латинские буквы, цифры и дефис.\n"
        "Отменить действие: /cancel"
    )
    await callback.answer()


@router.message(StateFilter(TrackingForm.number))
async def tracking_number_entered(message: Message, state: FSMContext, pool):
    try:
        normalized = normalize_tracking_number(message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ {escape(str(exc))}. Попробуйте ещё раз:")
        return

    try:
        client = await get_registered_client(pool, message.from_user.id)
        if client is None:
            await state.clear()
            await message.answer("Сначала нужно зарегистрироваться в Cargo Bot.")
            await begin_registration(message, state)
            return
        existing = await tracking_repository.get_tracking_by_normalized(pool, normalized)
    except Exception:
        logger.exception("Failed to check tracking number before confirmation")
        await message.answer("Не удалось проверить трек-номер. Попробуйте позже.")
        return
    if existing is not None:
        await message.answer(duplicate_message(existing["client_id"], client["id"]))
        return

    await state.update_data(tracking_number=normalized)
    await state.set_state(TrackingForm.confirm)
    await message.answer(
        "Проверьте трек-номер:\n\n"
        f"<code>{escape(normalized)}</code>\n\n"
        "После отправки продавцу убедитесь, что на посылке также указан "
        f"ваш Client ID: <code>{escape(str(client['client_code']))}</code>.",
        reply_markup=tracking_confirm_kb(),
    )


@router.callback_query(
    StateFilter(TrackingForm.confirm),
    F.data.startswith("tracking_confirm:"),
)
async def tracking_add_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    pool,
    bot: Bot,
    settings: Settings,
):
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Добавление трек-номера отменено.")
        await callback.answer()
        return
    if action == "restart":
        await state.set_state(TrackingForm.number)
        await callback.message.edit_text("Введите трек-номер заново:")
        await callback.answer()
        return
    if action != "save":
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    try:
        client = await get_registered_client(pool, callback.from_user.id)
    except Exception:
        logger.exception("Failed to load client before saving tracking")
        await callback.answer(
            "Не удалось загрузить профиль. Попробуйте позже.",
            show_alert=True,
        )
        return
    if client is None:
        await state.clear()
        await callback.answer("Сначала зарегистрируйтесь.", show_alert=True)
        return

    data = await state.get_data()
    normalized = data["tracking_number"]
    try:
        tracking = await tracking_repository.create_tracking(
            pool,
            client_id=client["id"],
            tracking_number=normalized,
            tracking_number_normalized=normalized,
        )
        if tracking is None:
            existing = await tracking_repository.get_tracking_by_normalized(
                pool, normalized
            )
            message_text = (
                duplicate_message(existing["client_id"], client["id"])
                if existing is not None
                else "Трек-номер не удалось сохранить. Попробуйте позже."
            )
            await callback.answer(message_text, show_alert=True)
            return
    except Exception:
        logger.exception(
            "Failed to save tracking number",
            extra={"client_id": client["id"]},
        )
        await callback.answer(
            "Не удалось сохранить трек-номер. Попробуйте позже.",
            show_alert=True,
        )
        return

    await state.clear()
    await callback.message.edit_text(
        "✅ Трек-номер сохранён.\n\n"
        f"<code>{escape(normalized)}</code>\n"
        "Статус: ⏳ Ожидается на складе"
    )
    await callback.answer("Трек-номер добавлен")

    if callback.from_user.id != settings.admin_id:
        try:
            await bot.send_message(
                settings.admin_id,
                format_admin_notification(client, normalized),
            )
        except Exception:
            logger.exception(
                "Failed to notify admin about tracking number",
                extra={"tracking_id": tracking["id"]},
            )


@router.callback_query(F.data == "tracking:list")
async def tracking_list(callback: CallbackQuery, state: FSMContext, pool):
    client = await require_callback_client(callback, state, pool)
    if client is None:
        return
    try:
        trackings = await tracking_repository.list_client_trackings(
            pool, client["id"], limit=20
        )
    except Exception:
        logger.exception(
            "Failed to list client trackings",
            extra={"client_id": client["id"]},
        )
        await callback.answer("Не удалось загрузить список.", show_alert=True)
        return

    if not trackings:
        await callback.message.answer(
            "У вас пока нет добавленных китайских трек-номеров."
        )
        await callback.answer()
        return

    await callback.message.answer("📋 <b>Ваши китайские трек-номера:</b>")
    for tracking in trackings:
        reply_markup = (
            tracking_cancel_kb(tracking["id"])
            if tracking["status"] == STATUS_DECLARED
            else None
        )
        await callback.message.answer(
            format_client_tracking(tracking),
            reply_markup=reply_markup,
        )
    await callback.answer()


@router.callback_query(F.data.startswith("tracking_cancel:"))
async def tracking_cancel_request(callback: CallbackQuery, state: FSMContext, pool):
    client = await require_callback_client(callback, state, pool)
    if client is None:
        return
    try:
        tracking_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    try:
        tracking = await tracking_repository.get_client_tracking(
            pool, tracking_id, client["id"]
        )
    except Exception:
        logger.exception(
            "Failed to load tracking before cancellation",
            extra={"tracking_id": tracking_id, "client_id": client["id"]},
        )
        await callback.answer("Не удалось загрузить трек-номер.", show_alert=True)
        return
    if tracking is None:
        await callback.answer("Трек-номер не найден.", show_alert=True)
        return
    if tracking["status"] != STATUS_DECLARED:
        await callback.answer("Этот трек-номер уже отменён.", show_alert=True)
        return

    await callback.message.answer(
        "Отменить трек-номер "
        f"<code>{escape(str(tracking['tracking_number']))}</code>?\n\n"
        "Запись сохранится в истории со статусом «Отменён».",
        reply_markup=tracking_cancel_confirm_kb(tracking_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tracking_cancel_confirm:"))
async def tracking_cancel_confirm(callback: CallbackQuery, state: FSMContext, pool):
    client = await require_callback_client(callback, state, pool)
    if client is None:
        return
    try:
        _, tracking_id_text, action = callback.data.split(":", 2)
        tracking_id = int(tracking_id_text)
    except (ValueError, IndexError):
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    if action == "no":
        await callback.message.edit_text("Отмена трек-номера не выполнена.")
        await callback.answer()
        return
    if action != "yes":
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    try:
        tracking = await tracking_repository.get_client_tracking(
            pool, tracking_id, client["id"]
        )
    except Exception:
        logger.exception(
            "Failed to verify tracking cancellation",
            extra={"tracking_id": tracking_id, "client_id": client["id"]},
        )
        await callback.answer("Не удалось загрузить трек-номер.", show_alert=True)
        return
    if tracking is None:
        await callback.answer("Трек-номер не найден.", show_alert=True)
        return
    if tracking["status"] != STATUS_DECLARED:
        await callback.answer("Этот трек-номер уже отменён.", show_alert=True)
        return

    try:
        cancelled = await tracking_repository.cancel_client_tracking(
            pool, tracking_id, client["id"]
        )
    except Exception:
        logger.exception(
            "Failed to cancel tracking",
            extra={"tracking_id": tracking_id, "client_id": client["id"]},
        )
        await callback.answer("Не удалось отменить трек-номер.", show_alert=True)
        return
    if cancelled is None:
        await callback.answer(
            "Не удалось отменить трек-номер. Обновите список.",
            show_alert=True,
        )
        return
    await callback.message.edit_text(
        "❌ Трек-номер отменён:\n"
        f"<code>{escape(str(cancelled['tracking_number']))}</code>"
    )
    await callback.answer("Трек-номер отменён")
