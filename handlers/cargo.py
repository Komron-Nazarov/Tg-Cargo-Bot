import logging

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from handlers.client import require_registered_client
from keyboards import cargo_photos_kb
from repositories import cargos as cargo_repository
from services.cargo_service import format_client_cargo


router = Router()
logger = logging.getLogger(__name__)


@router.message(StateFilter(None), F.text == "🚚 Мои грузы")
async def my_cargos(message: Message, state: FSMContext, pool):
    try:
        client = await require_registered_client(message, state, pool)
        if client is None:
            return
        cargos = await cargo_repository.list_client_cargos(pool, client["id"], limit=20)
    except Exception:
        logger.exception("Failed to list client cargos")
        await message.answer("Не удалось загрузить грузы. Попробуйте позже.")
        return
    if not cargos:
        await message.answer("У вас пока нет грузов, принятых на китайском складе.")
        return
    await message.answer("🚚 <b>Ваши грузы:</b>")
    for cargo in cargos:
        reply_markup = cargo_photos_kb(cargo["cargo_code"]) if cargo["photos_count"] else None
        await message.answer(format_client_cargo(cargo), reply_markup=reply_markup)


@router.callback_query(F.data.startswith("cargo_photos:"))
async def show_cargo_photos(callback: CallbackQuery, pool, bot: Bot):
    cargo_code = callback.data.split(":", 1)[1]
    try:
        cargo = await cargo_repository.get_client_cargo_by_code(
            pool,
            callback.from_user.id,
            cargo_code,
        )
        if cargo is None:
            await callback.answer("Cargo не найден или вам недоступен.", show_alert=True)
            return
        photos = await cargo_repository.get_cargo_photos(pool, cargo["id"])
    except Exception:
        logger.exception("Failed to load client cargo photos")
        await callback.answer("Не удалось загрузить фотографии.", show_alert=True)
        return
    for photo in photos:
        await bot.send_photo(callback.message.chat.id, photo["telegram_file_id"])
    await callback.answer(f"Фотографий: {len(photos)}")
