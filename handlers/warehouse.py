import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from filters import IsAdmin
from keyboards import (
    warehouse_confirm_kb,
    warehouse_photos_done_kb,
    warehouse_start_kb,
)
from repositories import cargos as cargo_repository
from services.cargo_service import (
    format_admin_cargo,
    format_client_notification,
    format_receipt_candidate,
    format_receipt_summary,
    normalize_cargo_code,
    parse_pieces_count,
    parse_volume,
    parse_weight,
    validate_description,
    validate_photos,
)
from services.tracking_service import normalize_tracking_number
from states import WarehouseReceiptForm


router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())
logger = logging.getLogger(__name__)


def _tracking_block_reason(tracking) -> str | None:
    if tracking["status"] == cargo_repository.STATUS_CANCELLED:
        return "Этот трек-номер отменён и не может быть принят."
    if tracking["status"] == cargo_repository.STATUS_RECEIVED or tracking["cargo_id"]:
        return "Этот трек-номер уже принят на склад."
    return None


@router.message(Command("receive"))
async def receive_tracking(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    pool,
):
    query = (command.args or "").strip()
    if not query:
        await message.answer("Использование: /receive &lt;Chinese Tracking Number&gt;")
        return
    try:
        normalized = normalize_tracking_number(query)
    except ValueError:
        await message.answer("Некорректный трек-номер.")
        return
    try:
        tracking = await cargo_repository.get_receipt_tracking_by_number(pool, normalized)
    except Exception:
        logger.exception("Failed to load tracking for warehouse receipt")
        await message.answer("Не удалось загрузить трек-номер. Попробуйте позже.")
        return
    if tracking is None:
        await message.answer("Трек-номер не найден.")
        return
    reason = _tracking_block_reason(tracking)
    if reason:
        await message.answer(reason)
        return

    await state.clear()
    await state.update_data(
        tracking_id=tracking["id"],
        tracking_number=tracking["tracking_number"],
        client_code=tracking["client_code"],
    )
    await state.set_state(WarehouseReceiptForm.start_confirm)
    await message.answer(
        format_receipt_candidate(tracking),
        reply_markup=warehouse_start_kb(tracking["id"]),
    )


@router.callback_query(
    StateFilter(WarehouseReceiptForm.start_confirm),
    F.data.startswith("warehouse_start:"),
)
async def warehouse_start(callback: CallbackQuery, state: FSMContext, pool):
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Складская приёмка отменена.")
        await callback.answer()
        return
    try:
        tracking_id = int(action)
    except ValueError:
        await callback.answer("Некорректная команда.", show_alert=True)
        return
    data = await state.get_data()
    if data.get("tracking_id") != tracking_id:
        await callback.answer("Данные приёмки устарели.", show_alert=True)
        return
    try:
        tracking = await cargo_repository.get_receipt_tracking_by_id(pool, tracking_id)
    except Exception:
        logger.exception("Failed to recheck tracking before warehouse receipt")
        await callback.answer("Не удалось проверить трек-номер.", show_alert=True)
        return
    if tracking is None:
        await state.clear()
        await callback.answer("Трек-номер не найден.", show_alert=True)
        return
    reason = _tracking_block_reason(tracking)
    if reason:
        await state.clear()
        await callback.answer(reason, show_alert=True)
        return
    await state.set_state(WarehouseReceiptForm.description)
    await callback.message.edit_text(
        "Введите краткое описание содержимого (2–500 символов).\n"
        "Если описание пока не нужно — /skip.\n"
        "Отменить приёмку — /cancel."
    )
    await callback.answer()


@router.message(Command("cancel"), StateFilter(WarehouseReceiptForm))
async def cancel_warehouse_receipt(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Складская приёмка отменена. Данные не изменены.")


@router.message(StateFilter(WarehouseReceiptForm.description))
async def receipt_description(message: Message, state: FSMContext):
    try:
        description = validate_description(message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ {escape(str(exc))}. Попробуйте ещё раз или /skip:")
        return
    await state.update_data(description=description)
    await state.set_state(WarehouseReceiptForm.weight)
    await message.answer("Введите фактический вес в кг, например: 2.5")


@router.message(StateFilter(WarehouseReceiptForm.weight))
async def receipt_weight(message: Message, state: FSMContext):
    try:
        weight = parse_weight(message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ {escape(str(exc))}. Введите вес ещё раз:")
        return
    await state.update_data(actual_weight_kg=weight)
    await state.set_state(WarehouseReceiptForm.volume)
    await message.answer(
        "Введите объём в м³, например: 0.035.\n"
        "Если объём ещё не измерен — /skip."
    )


@router.message(StateFilter(WarehouseReceiptForm.volume))
async def receipt_volume(message: Message, state: FSMContext):
    try:
        volume = parse_volume(message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ {escape(str(exc))}. Попробуйте ещё раз или /skip:")
        return
    await state.update_data(volume_m3=volume)
    await state.set_state(WarehouseReceiptForm.pieces)
    await message.answer("Введите количество мест — целое число от 1 до 10000:")


@router.message(StateFilter(WarehouseReceiptForm.pieces))
async def receipt_pieces(message: Message, state: FSMContext):
    try:
        pieces = parse_pieces_count(message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ {escape(str(exc))}.")
        return
    await state.update_data(pieces_count=pieces, photos=[])
    await state.set_state(WarehouseReceiptForm.photos)
    await message.answer(
        "Отправьте от 1 до 10 фотографий груза.\n"
        "Фотографии отправляйте по одной.",
        reply_markup=warehouse_photos_done_kb(),
    )


async def _show_receipt_summary(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    validate_photos(data.get("photos", []))
    await state.set_state(WarehouseReceiptForm.confirm)
    await message.answer(
        format_receipt_summary(data),
        reply_markup=warehouse_confirm_kb(data["tracking_id"]),
    )


@router.message(StateFilter(WarehouseReceiptForm.photos), F.photo)
async def receipt_photo(message: Message, state: FSMContext):
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
        await _show_receipt_summary(message, state)


@router.callback_query(
    StateFilter(WarehouseReceiptForm.photos),
    F.data == "warehouse_photos:done",
)
async def receipt_photos_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("photos"):
        await callback.answer("Добавьте хотя бы одну фотографию.", show_alert=True)
        return
    await _show_receipt_summary(callback.message, state)
    await callback.answer()


@router.message(StateFilter(WarehouseReceiptForm.photos))
async def receipt_photo_required(message: Message):
    await message.answer("Отправьте фотографию груза или нажмите кнопку завершения.")


@router.callback_query(
    StateFilter(WarehouseReceiptForm.confirm),
    F.data.startswith("warehouse_confirm:"),
)
async def receipt_confirm_action(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Складская приёмка отменена. Данные не изменены.")
        await callback.answer()
        return
    if action == "restart":
        data = await state.get_data()
        await state.set_data(
            {
                "tracking_id": data["tracking_id"],
                "tracking_number": data["tracking_number"],
                "client_code": data["client_code"],
            }
        )
        await state.set_state(WarehouseReceiptForm.description)
        await callback.message.edit_text(
            "Введите описание заново (2–500 символов) или /skip:"
        )
        await callback.answer()


@router.callback_query(
    StateFilter(WarehouseReceiptForm.confirm),
    F.data.startswith("warehouse_accept:"),
)
async def accept_cargo(
    callback: CallbackQuery,
    state: FSMContext,
    pool,
    bot: Bot,
):
    try:
        tracking_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректная команда.", show_alert=True)
        return
    data = await state.get_data()
    if data.get("tracking_id") != tracking_id:
        await callback.answer("Данные приёмки устарели.", show_alert=True)
        return
    try:
        validate_photos(data.get("photos", []))
        cargo = await cargo_repository.create_cargo_from_tracking(
            pool,
            tracking_id=tracking_id,
            description=data.get("description"),
            actual_weight_kg=data["actual_weight_kg"],
            volume_m3=data.get("volume_m3"),
            pieces_count=data["pieces_count"],
            photos=data["photos"],
            received_by_telegram_id=callback.from_user.id,
        )
    except cargo_repository.TrackingCancelledError:
        await state.clear()
        await callback.answer(
            "Этот трек-номер отменён и не может быть принят.", show_alert=True
        )
        return
    except cargo_repository.TrackingAlreadyReceivedError:
        await state.clear()
        await callback.answer("Этот трек-номер уже принят на склад.", show_alert=True)
        return
    except cargo_repository.TrackingNotFoundError:
        await state.clear()
        await callback.answer("Трек-номер не найден.", show_alert=True)
        return
    except Exception:
        logger.exception("Failed to create cargo transactionally", extra={"tracking_id": tracking_id})
        await callback.answer("Не удалось сохранить приёмку. Попробуйте позже.", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_text(
        "✅ Груз принят на склад.\n\n"
        f"Cargo ID: <code>{escape(str(cargo['cargo_code']))}</code>"
    )
    await callback.answer("Cargo создан")

    try:
        await bot.send_message(cargo["telegram_user_id"], format_client_notification(cargo))
        photos = await cargo_repository.get_cargo_photos(pool, cargo["id"])
        for photo in photos:
            await bot.send_photo(cargo["telegram_user_id"], photo["telegram_file_id"])
    except Exception:
        logger.exception(
            "Failed to notify client about received cargo",
            extra={"cargo_id": cargo["id"]},
        )


@router.callback_query(F.data.startswith("warehouse_accept:"))
async def repeated_accept(callback: CallbackQuery, pool):
    try:
        tracking_id = int(callback.data.split(":", 1)[1])
        tracking = await cargo_repository.get_receipt_tracking_by_id(pool, tracking_id)
    except (ValueError, IndexError):
        await callback.answer("Некорректная команда.", show_alert=True)
        return
    except Exception:
        logger.exception("Failed to check repeated cargo acceptance")
        await callback.answer("Не удалось проверить Cargo.", show_alert=True)
        return
    if tracking and tracking["cargo_code"]:
        await callback.answer(
            f"Уже создан Cargo ID: {tracking['cargo_code']}", show_alert=True
        )
    else:
        await callback.answer("Приёмка уже завершена или отменена.", show_alert=True)


@router.message(Command("cargos"))
async def list_cargos(message: Message, pool):
    try:
        cargos = await cargo_repository.list_recent_cargos(pool, limit=20)
    except Exception:
        logger.exception("Failed to list cargos for admin")
        await message.answer("Не удалось загрузить Cargo. Попробуйте позже.")
        return
    if not cargos:
        await message.answer("Принятых Cargo пока нет.")
        return
    await message.answer("📋 <b>Последние принятые Cargo:</b>")
    for cargo in cargos:
        await message.answer(format_admin_cargo(cargo))


@router.message(Command("cargo"))
async def find_cargo(message: Message, command: CommandObject, pool, bot: Bot):
    try:
        cargo_code = normalize_cargo_code(command.args or "")
    except ValueError:
        await message.answer("Использование: /cargo &lt;Cargo ID&gt;")
        return
    try:
        cargo = await cargo_repository.get_cargo_by_code(pool, cargo_code)
        photos = (
            await cargo_repository.get_cargo_photos(pool, cargo["id"])
            if cargo is not None
            else []
        )
    except Exception:
        logger.exception("Failed to find cargo for admin")
        await message.answer("Не удалось загрузить Cargo. Попробуйте позже.")
        return
    if cargo is None:
        await message.answer("Cargo не найден.")
        return
    await message.answer(format_admin_cargo(cargo, full=True))
    for photo in photos:
        await bot.send_photo(message.chat.id, photo["telegram_file_id"])
