import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from handlers.client import begin_registration, get_registered_client, require_registered_client
from repositories import trackings as tracking_repository
from services.tracking_service import format_client_tracking

router = Router()
logger = logging.getLogger(__name__)


async def _send_client_trackings(message: Message, client, pool) -> None:
    try:
        trackings = await tracking_repository.list_client_trackings(
            pool, client["id"], limit=20
        )
    except Exception:
        logger.exception(
            "Failed to list client trackings",
            extra={"client_id": client["id"]},
        )
        await message.answer("Не удалось загрузить трек-номера. Попробуйте позже.")
        return

    if not trackings:
        await message.answer(
            "🔎 <b>Мои китайские трек-номера</b>\n\n"
            "Компания пока не добавила для вас ни одного трек-номера. "
            "После добавления он появится здесь автоматически."
        )
        return

    await message.answer(
        "🔎 <b>Мои китайские трек-номера</b>\n\n"
        "Номера добавляет компания после получения данных от продавца."
    )
    for tracking in trackings:
        await message.answer(format_client_tracking(tracking))


@router.message(
    F.text.in_({"🔎 Мои трек-номера", "🔎 Китайские трек-номера"})
)
async def tracking_section(message: Message, state: FSMContext, pool):
    try:
        client = await require_registered_client(message, state, pool)
    except Exception:
        logger.exception("Failed to open tracking section")
        await message.answer("Не удалось загрузить профиль. Попробуйте позже.")
        return
    if client is not None:
        await _send_client_trackings(message, client, pool)


@router.callback_query(F.data == "tracking:list")
async def tracking_list_legacy(callback: CallbackQuery, state: FSMContext, pool):
    """Keep old inline list buttons functional after the client flow is simplified."""
    try:
        client = await get_registered_client(pool, callback.from_user.id)
    except Exception:
        logger.exception("Failed to load client for legacy tracking callback")
        await callback.answer("Не удалось загрузить профиль.", show_alert=True)
        return
    if client is None:
        await callback.message.answer("Сначала нужно зарегистрироваться в Cargo Bot.")
        await begin_registration(callback.message, state)
    else:
        await _send_client_trackings(callback.message, client, pool)
    await callback.answer()


@router.callback_query(F.data.startswith("tracking:"))
@router.callback_query(F.data.startswith("tracking_cancel"))
@router.callback_query(F.data.startswith("tracking_confirm:"))
async def disabled_client_tracking_action(callback: CallbackQuery, state: FSMContext):
    """Reject stale add/cancel buttons from messages sent by older bot versions."""
    await state.clear()
    await callback.answer(
        "Теперь трек-номера добавляет и исправляет компания.",
        show_alert=True,
    )
