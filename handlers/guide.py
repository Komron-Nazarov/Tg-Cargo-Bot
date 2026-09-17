from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import Settings
from keyboards import guide_kb
from services.guide_service import ADMIN_GUIDE, CLIENT_GUIDE, guide_page

router = Router()


@router.message(Command("guide"))
@router.message(F.text == "📖 Как пользоваться")
async def client_guide(message: Message):
    await message.answer(guide_page("client", 0), reply_markup=guide_kb("client", 0))


@router.message(Command("admin_guide"))
async def admin_guide(message: Message, settings: Settings):
    if message.from_user.id != settings.admin_id:
        return
    await message.answer(guide_page("admin", 0), reply_markup=guide_kb("admin", 0))


@router.callback_query(F.data.startswith("guide:"))
async def guide_navigation(callback: CallbackQuery, settings: Settings):
    try:
        _, kind, raw_index = callback.data.split(":", 2)
        index = int(raw_index)
        pages = CLIENT_GUIDE if kind == "client" else ADMIN_GUIDE if kind == "admin" else ()
        if not 0 <= index < len(pages):
            raise ValueError
    except (ValueError, AttributeError):
        await callback.answer("Страница недоступна.", show_alert=True)
        return
    if kind == "admin" and callback.from_user.id != settings.admin_id:
        await callback.answer("Только для администратора.", show_alert=True)
        return
    await callback.message.edit_text(
        guide_page(kind, index), reply_markup=guide_kb(kind, index)
    )
    await callback.answer()
