import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from config import Settings
from keyboards import (
    main_menu_kb,
    phone_kb,
    registration_cities_kb,
    registration_confirm_kb,
    registration_prompt_kb,
)
from repositories import clients as client_repository
from services.client_service import (
    format_profile,
    format_warehouse_address,
    normalize_phone,
)
from states import RegistrationForm

router = Router()
logger = logging.getLogger(__name__)


async def get_registered_client(pool, telegram_user_id: int):
    client = await client_repository.get_client_by_telegram_id(pool, telegram_user_id)
    if client is None or not client["is_active"]:
        return None
    return client


async def begin_registration(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(RegistrationForm.full_name)
    await message.answer(
        "📝 <b>Регистрация клиента</b>\n\n"
        "Введите имя и фамилию, например: Комрон Назаров.\n\n"
        "Отменить регистрацию: /cancel"
    )


async def require_registered_client(message: Message, state: FSMContext, pool):
    client = await get_registered_client(pool, message.from_user.id)
    if client is not None:
        return client
    await message.answer("Сначала нужно зарегистрироваться в Cargo Bot.")
    await begin_registration(message, state)
    return None


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, pool):
    await state.clear()
    client = await get_registered_client(pool, message.from_user.id)
    if client is None:
        await message.answer(
            "🚚 Привет! Это Cargo Bot.\n\n"
            "Для работы с доставкой сначала зарегистрируйтесь. После регистрации "
            "вы получите персональный Client ID для китайского склада.",
            reply_markup=registration_prompt_kb(),
        )
        return

    await message.answer(
        f"🚚 С возвращением! Ваш Client ID: "
        f"<code>{escape(str(client['client_code']))}</code>\n\n"
        "Выберите нужный раздел:",
        reply_markup=main_menu_kb(),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, pool):
    current_state = await state.get_state()
    if current_state is None:
        client = await get_registered_client(pool, message.from_user.id)
        if client is not None:
            await message.answer("Сейчас нечего отменять 🙂", reply_markup=main_menu_kb())
        else:
            await message.answer(
                "Сейчас нечего отменять 🙂",
                reply_markup=registration_prompt_kb(),
            )
        return

    is_registration = current_state.startswith(RegistrationForm.__name__)
    await state.clear()
    client = await get_registered_client(pool, message.from_user.id)
    if client is not None:
        text = "❌ Регистрация отменена." if is_registration else "❌ Заявка отменена."
        await message.answer(text, reply_markup=main_menu_kb())
    else:
        await message.answer(
            "❌ Регистрация отменена.",
            reply_markup=registration_prompt_kb(),
        )


@router.callback_query(F.data == "register:start")
async def registration_start(callback: CallbackQuery, state: FSMContext, pool):
    client = await get_registered_client(pool, callback.from_user.id)
    if client is not None:
        await callback.message.answer(
            "Вы уже зарегистрированы.",
            reply_markup=main_menu_kb(),
        )
        await callback.answer()
        return
    await begin_registration(callback.message, state)
    await callback.answer()


@router.message(StateFilter(RegistrationForm.full_name))
async def registration_name(message: Message, state: FSMContext):
    full_name = " ".join((message.text or "").split())
    parts = full_name.split()
    if len(parts) < 2 or any(len(part) < 2 for part in parts):
        await message.answer("Введите имя и фамилию, например: Комрон Назаров.")
        return
    if len(full_name) > 120:
        await message.answer("Имя слишком длинное. Введите имя и фамилию короче.")
        return

    await state.update_data(full_name=full_name)
    await state.set_state(RegistrationForm.phone)
    await message.answer(
        "📱 Отправьте свой номер кнопкой ниже или введите его вручную.",
        reply_markup=phone_kb(),
    )


@router.message(StateFilter(RegistrationForm.phone))
async def registration_phone(message: Message, state: FSMContext):
    if message.contact is not None:
        if (
            message.contact.user_id is not None
            and message.contact.user_id != message.from_user.id
        ):
            await message.answer("Отправьте именно свой номер телефона.")
            return
        raw_phone = message.contact.phone_number
    else:
        raw_phone = message.text or ""

    try:
        phone = normalize_phone(raw_phone)
    except ValueError:
        await message.answer("Введите корректный номер, например: +992900001122")
        return

    await state.update_data(phone=phone)
    await state.set_state(RegistrationForm.city)
    await message.answer("Номер сохранён.", reply_markup=ReplyKeyboardRemove())
    await message.answer(
        "📍 Выберите город получения:",
        reply_markup=registration_cities_kb(),
    )


@router.callback_query(
    StateFilter(RegistrationForm.city),
    F.data.startswith("register_city:"),
)
async def registration_city(callback: CallbackQuery, state: FSMContext):
    city = callback.data.split(":", 1)[1]
    if city == "other":
        await state.set_state(RegistrationForm.custom_city)
        await callback.message.edit_text("Введите город получения:")
        await callback.answer()
        return

    await state.update_data(delivery_city=city)
    await show_registration_confirmation(callback.message, state)
    await callback.answer()


@router.message(StateFilter(RegistrationForm.custom_city))
async def registration_custom_city(message: Message, state: FSMContext):
    city = " ".join((message.text or "").split())
    if not 2 <= len(city) <= 100:
        await message.answer("Введите корректное название города.")
        return
    await state.update_data(delivery_city=city)
    await show_registration_confirmation(message, state)


async def show_registration_confirmation(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(RegistrationForm.confirm)
    await message.answer(
        "Проверьте данные регистрации:\n\n"
        f"Имя: {escape(data['full_name'])}\n"
        f"Телефон: {escape(data['phone'])}\n"
        f"Город получения: {escape(data['delivery_city'])}\n\n"
        "Всё верно?",
        reply_markup=registration_confirm_kb(),
    )


@router.callback_query(
    StateFilter(RegistrationForm.confirm),
    F.data.startswith("register_confirm:"),
)
async def registration_confirm(callback: CallbackQuery, state: FSMContext, pool):
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Регистрация отменена.")
        await callback.answer()
        return
    if action == "restart":
        await state.clear()
        await state.set_state(RegistrationForm.full_name)
        await callback.message.edit_text("Введите имя и фамилию заново:")
        await callback.answer()
        return

    data = await state.get_data()
    try:
        client = await client_repository.create_client(
            pool,
            telegram_user_id=callback.from_user.id,
            telegram_username=callback.from_user.username,
            full_name=data["full_name"],
            phone=data["phone"],
            delivery_city=data["delivery_city"],
        )
    except Exception:
        logger.exception(
            "Failed to register client",
            extra={"telegram_user_id": callback.from_user.id},
        )
        await callback.answer("Не удалось завершить регистрацию. Попробуйте позже.", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_text(
        "✅ Регистрация завершена!\n\n"
        f"Ваш Client ID: <code>{escape(str(client['client_code']))}</code>\n\n"
        "Сохраните его: Client ID нужно указывать на посылках для китайского склада."
    )
    await callback.message.answer("Выберите нужный раздел:", reply_markup=main_menu_kb())
    await callback.answer()


@router.message(StateFilter(None), F.text == "👤 Мой профиль")
async def my_profile(message: Message, state: FSMContext, pool):
    client = await require_registered_client(message, state, pool)
    if client is not None:
        await message.answer(format_profile(client))


@router.message(StateFilter(None), F.text == "🏭 Адрес склада в Китае")
async def china_warehouse_address(
    message: Message,
    state: FSMContext,
    pool,
    settings: Settings,
):
    client = await require_registered_client(message, state, pool)
    if client is None:
        return
    await message.answer(
        format_warehouse_address(
            client_code=client["client_code"],
            address=settings.china_warehouse_address,
            recipient=settings.china_warehouse_recipient,
            phone=settings.china_warehouse_phone,
        )
    )
