import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from filters import IsAdmin
from handlers.client import require_registered_client
from keyboards import (
    consolidation_confirm_kb,
    consolidation_photos_done_kb,
    consolidation_photos_kb,
    consolidation_start_kb,
)
from repositories import consolidations as consolidation_repository
from services.cargo_service import (
    parse_pieces_count,
    parse_volume,
    parse_weight,
    validate_description,
    validate_photos,
)
from services.consolidation_service import (
    format_admin_consolidation,
    format_client_consolidation,
    format_client_notification,
    format_consolidation_candidate,
    format_consolidation_summary,
    normalize_consolidation_code,
    parse_cargo_codes,
)
from states import ConsolidationForm


router = Router()
admin_router = Router()
admin_router.message.filter(IsAdmin())
admin_router.callback_query.filter(IsAdmin())
logger = logging.getLogger(__name__)


def _candidate_error_text(exc: Exception) -> str:
    if isinstance(exc, consolidation_repository.CargoNotFoundError):
        return f"Cargo {escape(exc.cargo_code)} не найден."
    if isinstance(exc, consolidation_repository.CargoDifferentClientsError):
        return "Нельзя объединить Cargo разных клиентов."
    if isinstance(exc, consolidation_repository.CargoAlreadyConsolidatedError):
        if exc.consolidation_code:
            return (
                f"Cargo {escape(exc.cargo_code)} уже входит в консолидацию "
                f"{escape(exc.consolidation_code)}."
            )
        return f"Cargo {escape(exc.cargo_code)} уже консолидирован."
    if isinstance(exc, consolidation_repository.CargoUnavailableError):
        return f"Cargo {escape(exc.cargo_code)} сейчас нельзя консолидировать."
    return "Не удалось проверить Cargo."


async def _load_candidates(pool, cargo_codes):
    rows = await consolidation_repository.get_cargos_for_consolidation(pool, cargo_codes)
    return consolidation_repository.validate_candidates(cargo_codes, rows)


@admin_router.message(Command("consolidate"))
async def start_consolidation(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    pool,
):
    try:
        cargo_codes = parse_cargo_codes(command.args or "")
    except ValueError as exc:
        await message.answer(
            f"❌ {escape(str(exc))}.\n"
            "Использование: /consolidate CG000001 CG000002"
        )
        return
    try:
        cargos = await _load_candidates(pool, cargo_codes)
    except (
        consolidation_repository.CargoNotFoundError,
        consolidation_repository.CargoDifferentClientsError,
        consolidation_repository.CargoAlreadyConsolidatedError,
        consolidation_repository.CargoUnavailableError,
    ) as exc:
        await message.answer(_candidate_error_text(exc))
        return
    except Exception:
        logger.exception("Failed to load cargos before consolidation")
        await message.answer("Не удалось проверить Cargo. Попробуйте позже.")
        return

    await state.clear()
    await state.update_data(
        cargo_codes=cargo_codes,
        tracking_numbers=[cargo["tracking_number"] for cargo in cargos],
        client_code=cargos[0]["client_code"],
    )
    await state.set_state(ConsolidationForm.start_confirm)
    await message.answer(
        format_consolidation_candidate(cargos),
        reply_markup=consolidation_start_kb(cargo_codes[0]),
    )


@admin_router.callback_query(
    StateFilter(ConsolidationForm.start_confirm),
    F.data.startswith("consolidation_start:"),
)
async def confirm_consolidation_start(
    callback: CallbackQuery,
    state: FSMContext,
    pool,
):
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Консолидация отменена. Данные не изменены.")
        await callback.answer()
        return
    data = await state.get_data()
    cargo_codes = data.get("cargo_codes", [])
    if not cargo_codes or action != cargo_codes[0]:
        await callback.answer("Данные консолидации устарели.", show_alert=True)
        return
    try:
        await _load_candidates(pool, cargo_codes)
    except (
        consolidation_repository.CargoNotFoundError,
        consolidation_repository.CargoDifferentClientsError,
        consolidation_repository.CargoAlreadyConsolidatedError,
        consolidation_repository.CargoUnavailableError,
    ) as exc:
        await state.clear()
        await callback.answer(_candidate_error_text(exc), show_alert=True)
        return
    except Exception:
        logger.exception("Failed to recheck cargos before consolidation")
        await callback.answer("Не удалось проверить Cargo.", show_alert=True)
        return
    await state.set_state(ConsolidationForm.description)
    await callback.message.edit_text(
        "Введите описание объединённой упаковки (2–500 символов).\n"
        "Если описание не нужно — /skip.\n"
        "Отменить консолидацию — /cancel."
    )
    await callback.answer()


@admin_router.message(Command("cancel"), StateFilter(ConsolidationForm))
async def cancel_consolidation(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Консолидация отменена. Данные не изменены.")


@admin_router.message(StateFilter(ConsolidationForm.description))
async def consolidation_description(message: Message, state: FSMContext):
    try:
        description = validate_description(message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ {escape(str(exc))}. Попробуйте ещё раз или /skip:")
        return
    await state.update_data(description=description)
    await state.set_state(ConsolidationForm.weight)
    await message.answer("Введите итоговый вес после консолидации в кг:")


@admin_router.message(StateFilter(ConsolidationForm.weight))
async def consolidation_weight(message: Message, state: FSMContext):
    try:
        weight = parse_weight(message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ {escape(str(exc))}. Введите вес ещё раз:")
        return
    await state.update_data(final_weight_kg=weight)
    await state.set_state(ConsolidationForm.volume)
    await message.answer("Введите итоговый объём в м³ или /skip:")


@admin_router.message(StateFilter(ConsolidationForm.volume))
async def consolidation_volume(message: Message, state: FSMContext):
    try:
        volume = parse_volume(message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ {escape(str(exc))}. Попробуйте ещё раз или /skip:")
        return
    await state.update_data(final_volume_m3=volume)
    await state.set_state(ConsolidationForm.pieces)
    await message.answer("Введите итоговое количество мест — от 1 до 10000:")


@admin_router.message(StateFilter(ConsolidationForm.pieces))
async def consolidation_pieces(message: Message, state: FSMContext):
    try:
        pieces = parse_pieces_count(message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ {escape(str(exc))}.")
        return
    await state.update_data(final_pieces_count=pieces, photos=[])
    await state.set_state(ConsolidationForm.photos)
    await message.answer(
        "Отправьте от 1 до 10 фотографий результата консолидации.",
        reply_markup=consolidation_photos_done_kb(),
    )


async def _show_summary(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    validate_photos(data.get("photos", []))
    await state.set_state(ConsolidationForm.confirm)
    await message.answer(
        format_consolidation_summary(data),
        reply_markup=consolidation_confirm_kb(data["cargo_codes"][0]),
    )


@admin_router.message(StateFilter(ConsolidationForm.photos), F.photo)
async def consolidation_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = list(data.get("photos", []))
    photo = message.photo[-1]
    if any(item["file_unique_id"] == photo.file_unique_id for item in photos):
        await message.answer("Эта фотография уже добавлена.")
        return
    if len(photos) >= 10:
        await message.answer("Уже добавлено максимальное количество фотографий: 10/10.")
        return
    photos.append({"file_id": photo.file_id, "file_unique_id": photo.file_unique_id})
    await state.update_data(photos=photos)
    await message.answer(f"Добавлено фотографий: {len(photos)}/10")
    if len(photos) == 10:
        await _show_summary(message, state)


@admin_router.callback_query(
    StateFilter(ConsolidationForm.photos),
    F.data == "consolidation_photos:done",
)
async def consolidation_photos_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("photos"):
        await callback.answer("Добавьте хотя бы одну фотографию.", show_alert=True)
        return
    await _show_summary(callback.message, state)
    await callback.answer()


@admin_router.message(StateFilter(ConsolidationForm.photos))
async def consolidation_photo_required(message: Message):
    await message.answer("Отправьте фотографию или нажмите кнопку завершения.")


@admin_router.callback_query(
    StateFilter(ConsolidationForm.confirm),
    F.data.startswith("consolidation_confirm:"),
)
async def consolidation_confirm_action(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Консолидация отменена. Данные не изменены.")
        await callback.answer()
        return
    if action == "restart":
        data = await state.get_data()
        await state.set_data(
            {
                "cargo_codes": data["cargo_codes"],
                "tracking_numbers": data["tracking_numbers"],
                "client_code": data["client_code"],
            }
        )
        await state.set_state(ConsolidationForm.description)
        await callback.message.edit_text("Введите описание заново или /skip:")
        await callback.answer()


@admin_router.callback_query(
    StateFilter(ConsolidationForm.confirm),
    F.data.startswith("consolidation_accept:"),
)
async def create_consolidation(
    callback: CallbackQuery,
    state: FSMContext,
    pool,
    bot: Bot,
):
    data = await state.get_data()
    cargo_codes = data.get("cargo_codes", [])
    callback_code = callback.data.split(":", 1)[1]
    if not cargo_codes or callback_code != cargo_codes[0]:
        await callback.answer("Данные консолидации устарели.", show_alert=True)
        return
    try:
        validate_photos(data.get("photos", []))
        consolidation = await consolidation_repository.create_consolidation(
            pool,
            cargo_codes=cargo_codes,
            description=data.get("description"),
            final_weight_kg=data["final_weight_kg"],
            final_volume_m3=data.get("final_volume_m3"),
            final_pieces_count=data["final_pieces_count"],
            photos=data["photos"],
            consolidated_by_telegram_id=callback.from_user.id,
        )
    except (
        consolidation_repository.CargoNotFoundError,
        consolidation_repository.CargoDifferentClientsError,
        consolidation_repository.CargoAlreadyConsolidatedError,
        consolidation_repository.CargoUnavailableError,
    ) as exc:
        await state.clear()
        await callback.answer(_candidate_error_text(exc), show_alert=True)
        return
    except Exception:
        logger.exception("Failed to create consolidation transactionally")
        await callback.answer("Не удалось сохранить консолидацию. Попробуйте позже.", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_text(
        "✅ Консолидация создана.\n\n"
        f"Consolidation ID: <code>{escape(str(consolidation['consolidation_code']))}</code>"
    )
    await callback.answer("Консолидация создана")
    try:
        await bot.send_message(
            consolidation["telegram_user_id"],
            format_client_notification(consolidation),
        )
        photos = await consolidation_repository.get_consolidation_photos(
            pool, consolidation["id"]
        )
        for photo in photos:
            await bot.send_photo(
                consolidation["telegram_user_id"], photo["telegram_file_id"]
            )
    except Exception:
        logger.exception(
            "Failed to notify client about consolidation",
            extra={"consolidation_id": consolidation["id"]},
        )


@admin_router.callback_query(F.data.startswith("consolidation_accept:"))
async def repeated_consolidation(callback: CallbackQuery, pool):
    cargo_code = callback.data.split(":", 1)[1]
    try:
        consolidation = await consolidation_repository.get_consolidation_for_cargo(
            pool, cargo_code
        )
    except Exception:
        logger.exception("Failed to check repeated consolidation")
        await callback.answer("Не удалось проверить консолидацию.", show_alert=True)
        return
    if consolidation:
        await callback.answer(
            f"Уже создана консолидация {consolidation['consolidation_code']}",
            show_alert=True,
        )
    else:
        await callback.answer("Консолидация отменена или не завершена.", show_alert=True)


@admin_router.message(Command("consolidations"))
async def list_consolidations(message: Message, pool):
    try:
        rows = await consolidation_repository.list_recent_consolidations(pool, limit=20)
    except Exception:
        logger.exception("Failed to list consolidations for admin")
        await message.answer("Не удалось загрузить консолидации. Попробуйте позже.")
        return
    if not rows:
        await message.answer("Готовых консолидаций пока нет.")
        return
    await message.answer("📋 <b>Последние консолидации:</b>")
    for row in rows:
        await message.answer(format_admin_consolidation(row))


@admin_router.message(Command("consolidation"))
async def find_consolidation(
    message: Message,
    command: CommandObject,
    pool,
    bot: Bot,
):
    try:
        code = normalize_consolidation_code(command.args or "")
    except ValueError:
        await message.answer("Использование: /consolidation &lt;Consolidation ID&gt;")
        return
    try:
        row = await consolidation_repository.get_consolidation_by_code(pool, code)
        photos = (
            await consolidation_repository.get_consolidation_photos(pool, row["id"])
            if row is not None
            else []
        )
    except Exception:
        logger.exception("Failed to find consolidation for admin")
        await message.answer("Не удалось загрузить консолидацию. Попробуйте позже.")
        return
    if row is None:
        await message.answer("Консолидация не найдена.")
        return
    await message.answer(format_admin_consolidation(row, full=True))
    for photo in photos:
        await bot.send_photo(message.chat.id, photo["telegram_file_id"])


@router.message(StateFilter(None), F.text == "🔗 Мои консолидации")
async def my_consolidations(message: Message, state: FSMContext, pool):
    try:
        client = await require_registered_client(message, state, pool)
        if client is None:
            return
        rows = await consolidation_repository.list_client_consolidations(
            pool, client["id"], limit=20
        )
    except Exception:
        logger.exception("Failed to list client consolidations")
        await message.answer("Не удалось загрузить консолидации. Попробуйте позже.")
        return
    if not rows:
        await message.answer("У вас пока нет консолидированных грузов.")
        return
    await message.answer("🔗 <b>Ваши консолидации:</b>")
    for row in rows:
        reply_markup = (
            consolidation_photos_kb(row["consolidation_code"])
            if row["photos_count"]
            else None
        )
        await message.answer(
            format_client_consolidation(row), reply_markup=reply_markup
        )


@router.callback_query(F.data.startswith("consolidation_view_photos:"))
async def show_consolidation_photos(callback: CallbackQuery, pool, bot: Bot):
    code = callback.data.split(":", 1)[1]
    try:
        row = await consolidation_repository.get_client_consolidation_by_code(
            pool, callback.from_user.id, code
        )
        if row is None:
            await callback.answer(
                "Консолидация не найдена или вам недоступна.", show_alert=True
            )
            return
        photos = await consolidation_repository.get_consolidation_photos(
            pool, row["id"]
        )
    except Exception:
        logger.exception("Failed to load consolidation photos for client")
        await callback.answer("Не удалось загрузить фотографии.", show_alert=True)
        return
    for photo in photos:
        await bot.send_photo(callback.message.chat.id, photo["telegram_file_id"])
    await callback.answer(f"Фотографий: {len(photos)}")


router.include_router(admin_router)
