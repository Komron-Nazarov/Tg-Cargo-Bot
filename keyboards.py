from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

MAIN_MENU_BUTTONS = ["📦 Новая заявка", "📋 Мои заявки"]

COUNTRIES = ["🇹🇯 Таджикистан", "🇨🇳 Китай", "🇹🇷 Турция"]


def main_menu_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    for text in MAIN_MENU_BUTTONS:
        builder.button(text=text)
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def countries_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for country in COUNTRIES:
        builder.button(text=country, callback_data=f"country:{country}")
    builder.button(text="✏️ Другое", callback_data="country:other")
    builder.adjust(2)
    return builder.as_markup()


def confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="confirm:yes")
    builder.button(text="✏️ Начать заново", callback_data="confirm:restart")
    builder.button(text="❌ Отмена", callback_data="confirm:cancel")
    builder.adjust(1)
    return builder.as_markup()


def order_status_kb(order_id: int, current_status: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if current_status != "in_progress":
        builder.button(text="🔄 В работу", callback_data=f"status:{order_id}:in_progress")
    if current_status != "done":
        builder.button(text="✅ Готово", callback_data=f"status:{order_id}:done")
    builder.adjust(1)
    return builder.as_markup()