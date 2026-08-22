from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

MAIN_MENU_BUTTONS = [
    "📦 Новая заявка",
    "📋 Мои заявки",
    "👤 Мой профиль",
    "🏭 Адрес склада в Китае",
    "🔎 Китайские трек-номера",
    "🚚 Мои грузы",
    "🔗 Мои консолидации",
]

COUNTRIES = ["🇹🇯 Таджикистан", "🇨🇳 Китай", "🇹🇷 Турция"]


def main_menu_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    for text in MAIN_MENU_BUTTONS:
        builder.button(text=text)
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def registration_prompt_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Зарегистрироваться", callback_data="register:start")
    return builder.as_markup()


def phone_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="📱 Отправить мой номер", request_contact=True)
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def registration_cities_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Душанбе", callback_data="register_city:Душанбе")
    builder.button(text="Худжанд", callback_data="register_city:Худжанд")
    builder.button(text="Другой город", callback_data="register_city:other")
    builder.adjust(2, 1)
    return builder.as_markup()


def registration_confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="register_confirm:yes")
    builder.button(text="✏️ Начать заново", callback_data="register_confirm:restart")
    builder.button(text="❌ Отмена", callback_data="register_confirm:cancel")
    builder.adjust(1)
    return builder.as_markup()


def tracking_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить трек-номер", callback_data="tracking:add")
    builder.button(text="📋 Мои трек-номера", callback_data="tracking:list")
    builder.adjust(1)
    return builder.as_markup()


def tracking_confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Сохранить", callback_data="tracking_confirm:save")
    builder.button(text="✏️ Ввести заново", callback_data="tracking_confirm:restart")
    builder.button(text="❌ Отмена", callback_data="tracking_confirm:cancel")
    builder.adjust(1)
    return builder.as_markup()


def tracking_cancel_kb(tracking_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="❌ Отменить трек-номер",
        callback_data=f"tracking_cancel:{tracking_id}",
    )
    return builder.as_markup()


def tracking_cancel_confirm_kb(tracking_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Да, отменить",
        callback_data=f"tracking_cancel_confirm:{tracking_id}:yes",
    )
    builder.button(
        text="↩️ Нет",
        callback_data=f"tracking_cancel_confirm:{tracking_id}:no",
    )
    builder.adjust(1)
    return builder.as_markup()


def warehouse_start_kb(tracking_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Начать приёмку",
        callback_data=f"warehouse_start:{tracking_id}",
    )
    builder.button(text="❌ Отмена", callback_data="warehouse_start:cancel")
    builder.adjust(1)
    return builder.as_markup()


def warehouse_photos_done_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Завершить добавление фотографий",
        callback_data="warehouse_photos:done",
    )
    return builder.as_markup()


def warehouse_confirm_kb(tracking_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Принять и создать Cargo ID",
        callback_data=f"warehouse_accept:{tracking_id}",
    )
    builder.button(text="✏️ Начать заново", callback_data="warehouse_confirm:restart")
    builder.button(text="❌ Отмена", callback_data="warehouse_confirm:cancel")
    builder.adjust(1)
    return builder.as_markup()


def cargo_photos_kb(cargo_code: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📷 Показать фотографии",
        callback_data=f"cargo_photos:{cargo_code}",
    )
    return builder.as_markup()


def consolidation_start_kb(first_cargo_code: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Начать консолидацию",
        callback_data=f"consolidation_start:{first_cargo_code}",
    )
    builder.button(text="❌ Отмена", callback_data="consolidation_start:cancel")
    builder.adjust(1)
    return builder.as_markup()


def consolidation_photos_done_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Завершить добавление фотографий",
        callback_data="consolidation_photos:done",
    )
    return builder.as_markup()


def consolidation_confirm_kb(first_cargo_code: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Создать консолидацию",
        callback_data=f"consolidation_accept:{first_cargo_code}",
    )
    builder.button(
        text="✏️ Начать заново",
        callback_data="consolidation_confirm:restart",
    )
    builder.button(text="❌ Отмена", callback_data="consolidation_confirm:cancel")
    builder.adjust(1)
    return builder.as_markup()


def consolidation_photos_kb(consolidation_code: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📷 Показать фотографии",
        callback_data=f"consolidation_view_photos:{consolidation_code}",
    )
    return builder.as_markup()


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
