import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from filters import IsAdmin
from handlers.client import require_registered_client
from keyboards import (
    shipment_advance_confirm_kb,
    shipment_advance_start_kb,
    shipment_confirm_kb,
    shipment_start_kb,
    shipment_transport_kb,
)
from repositories import shipments as shipment_repository
from services.shipment_service import (
    build_client_views,
    format_admin_shipment,
    format_client_shipment,
    format_dispatch_candidate,
    format_dispatch_summary,
    group_client_shipment_units,
    normalize_shipment_code,
    parse_dispatch_codes,
    validate_note,
    validate_reference,
    validate_transport_type,
)
from services.shipment_status_service import (
    FinalShipmentStatusError,
    format_advance_candidate,
    format_advance_summary,
    format_status_notification,
    next_shipment_status,
    shipment_status_label,
    validate_event_note,
)
from states import ShipmentAdvanceForm, ShipmentForm


router = Router()
admin_router = Router()
admin_router.message.filter(IsAdmin())
admin_router.callback_query.filter(IsAdmin())
logger = logging.getLogger(__name__)


def _object_name(code: str) -> str:
    return "Cargo" if code.startswith("CG") else "Consolidation"


def _candidate_error_text(exc: Exception) -> str:
    if isinstance(exc, shipment_repository.DispatchObjectNotFoundError):
        suffix = "не найден" if exc.code.startswith("CG") else "не найдена"
        return f"{_object_name(exc.code)} {escape(exc.code)} {suffix}."
    if isinstance(exc, shipment_repository.CargoInConsolidationError):
        return (
            f"Cargo {escape(exc.code)} уже входит в Consolidation "
            f"{escape(exc.consolidation_code)}. Добавьте Consolidation ID."
        )
    if isinstance(exc, shipment_repository.DispatchObjectAlreadyShippedError):
        shipment = escape(exc.shipment_code or "другое отправление")
        verb = "отправлен" if exc.code.startswith("CG") else "отправлена"
        return f"{_object_name(exc.code)} {escape(exc.code)} уже {verb} в Shipment {shipment}."
    if isinstance(exc, shipment_repository.DispatchObjectUnavailableError):
        return "Объект сейчас нельзя добавить в отправку."
    return "Не удалось проверить объекты отправки."


async def _load_candidates(pool, codes):
    rows = await shipment_repository.get_dispatch_candidates(pool, codes)
    return shipment_repository.validate_dispatch_items(codes, rows)


@admin_router.message(Command("dispatch"))
async def start_dispatch(message: Message, command: CommandObject, state: FSMContext, pool):
    try:
        codes = parse_dispatch_codes(command.args or "")
    except ValueError as exc:
        await message.answer(
            f"❌ {escape(str(exc))}.\nИспользование: /dispatch CG000001 CS000001"
        )
        return
    try:
        items = await _load_candidates(pool, codes)
    except (
        shipment_repository.DispatchObjectNotFoundError,
        shipment_repository.CargoInConsolidationError,
        shipment_repository.DispatchObjectAlreadyShippedError,
        shipment_repository.DispatchObjectUnavailableError,
    ) as exc:
        await message.answer(_candidate_error_text(exc))
        return
    except Exception:
        logger.exception("Failed to load shipment candidates")
        await message.answer("Не удалось проверить объекты отправки. Попробуйте позже.")
        return

    await state.clear()
    await state.update_data(codes=codes, items=[dict(item) for item in items])
    await state.set_state(ShipmentForm.start_confirm)
    await message.answer(
        format_dispatch_candidate(items), reply_markup=shipment_start_kb(codes[0])
    )


@admin_router.callback_query(
    StateFilter(ShipmentForm.start_confirm), F.data.startswith("shipment_start:")
)
async def confirm_dispatch_start(callback: CallbackQuery, state: FSMContext, pool):
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Оформление отправки отменено. Данные не изменены.")
        await callback.answer()
        return
    data = await state.get_data()
    codes = data.get("codes", [])
    if not codes or action != codes[0]:
        await callback.answer("Данные отправки устарели.", show_alert=True)
        return
    try:
        items = await _load_candidates(pool, codes)
    except (
        shipment_repository.DispatchObjectNotFoundError,
        shipment_repository.CargoInConsolidationError,
        shipment_repository.DispatchObjectAlreadyShippedError,
        shipment_repository.DispatchObjectUnavailableError,
    ) as exc:
        await state.clear()
        await callback.answer(_candidate_error_text(exc), show_alert=True)
        return
    except Exception:
        logger.exception("Failed to recheck shipment candidates")
        await callback.answer("Не удалось проверить объекты.", show_alert=True)
        return
    await state.update_data(items=[dict(item) for item in items])
    await state.set_state(ShipmentForm.transport)
    await callback.message.edit_text(
        "Выберите тип транспорта:", reply_markup=shipment_transport_kb()
    )
    await callback.answer()


@admin_router.message(Command("cancel"), StateFilter(ShipmentForm))
async def cancel_dispatch(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Оформление отправки отменено. Данные не изменены.")


@admin_router.callback_query(
    StateFilter(ShipmentForm.transport), F.data.startswith("shipment_transport:")
)
async def choose_transport(callback: CallbackQuery, state: FSMContext):
    try:
        transport = validate_transport_type(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный тип транспорта.", show_alert=True)
        return
    await state.update_data(transport_type=transport)
    await state.set_state(ShipmentForm.reference)
    await callback.message.edit_text(
        "Введите номер машины, контейнера, накладной или другой reference "
        "(2–100 символов). Если его нет — /skip."
    )
    await callback.answer()


@admin_router.message(StateFilter(ShipmentForm.reference))
async def enter_reference(message: Message, state: FSMContext):
    try:
        reference = validate_reference(message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ {escape(str(exc))}. Попробуйте ещё раз или /skip:")
        return
    await state.update_data(transport_reference=reference)
    await state.set_state(ShipmentForm.note)
    await message.answer("Введите примечание (2–500 символов) или /skip:")


async def _show_summary(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(ShipmentForm.confirm)
    await message.answer(
        format_dispatch_summary(data), reply_markup=shipment_confirm_kb(data["codes"][0])
    )


@admin_router.message(StateFilter(ShipmentForm.note))
async def enter_note(message: Message, state: FSMContext):
    try:
        note = validate_note(message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ {escape(str(exc))}. Попробуйте ещё раз или /skip:")
        return
    await state.update_data(note=note)
    await _show_summary(message, state)


@admin_router.callback_query(
    StateFilter(ShipmentForm.confirm), F.data.startswith("shipment_confirm:")
)
async def shipment_confirm_action(callback: CallbackQuery, state: FSMContext, pool):
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Оформление отправки отменено. Данные не изменены.")
        await callback.answer()
        return
    if action == "restart":
        data = await state.get_data()
        try:
            items = await _load_candidates(pool, data.get("codes", []))
        except Exception:
            logger.exception("Failed to restart shipment creation")
            await state.clear()
            await callback.answer("Объекты больше недоступны.", show_alert=True)
            return
        await state.set_data({"codes": data["codes"], "items": [dict(x) for x in items]})
        await state.set_state(ShipmentForm.transport)
        await callback.message.edit_text(
            "Выберите тип транспорта:", reply_markup=shipment_transport_kb()
        )
        await callback.answer()


@admin_router.callback_query(
    StateFilter(ShipmentForm.confirm), F.data.startswith("shipment_accept:")
)
async def create_shipment(callback: CallbackQuery, state: FSMContext, pool, bot: Bot):
    data = await state.get_data()
    codes = data.get("codes", [])
    callback_code = callback.data.split(":", 1)[1]
    if not codes or callback_code != codes[0]:
        await callback.answer("Данные отправки устарели.", show_alert=True)
        return
    try:
        shipment = await shipment_repository.create_shipment(
            pool,
            codes=codes,
            transport_type=validate_transport_type(data["transport_type"]),
            transport_reference=data.get("transport_reference"),
            note=data.get("note"),
            created_by_telegram_id=callback.from_user.id,
        )
        items = await shipment_repository.get_shipment_items(pool, shipment["id"])
    except (
        shipment_repository.DispatchObjectNotFoundError,
        shipment_repository.CargoInConsolidationError,
        shipment_repository.DispatchObjectAlreadyShippedError,
        shipment_repository.DispatchObjectUnavailableError,
    ) as exc:
        await state.clear()
        await callback.answer(_candidate_error_text(exc), show_alert=True)
        return
    except Exception:
        logger.exception("Failed to create shipment transactionally")
        await callback.answer("Не удалось сохранить отправку. Попробуйте позже.", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_text(
        "✅ Выезд из Китая зафиксирован.\n\n"
        f"Shipment ID: <code>{escape(str(shipment['shipment_code']))}</code>"
    )
    await callback.answer("Отправление создано")
    for view in build_client_views(shipment, items):
        try:
            await bot.send_message(
                view["telegram_user_id"], format_client_shipment(view, notification=True)
            )
        except Exception:
            logger.exception(
                "Failed to notify one client about shipment",
                extra={"shipment_id": shipment["id"]},
            )


@admin_router.callback_query(F.data.startswith("shipment_accept:"))
async def repeated_shipment(callback: CallbackQuery, pool):
    code = callback.data.split(":", 1)[1]
    try:
        shipment = await shipment_repository.get_shipment_for_object(pool, code)
    except Exception:
        logger.exception("Failed to check repeated shipment callback")
        await callback.answer("Не удалось проверить отправление.", show_alert=True)
        return
    if shipment:
        await callback.answer(
            f"Уже создано отправление {shipment['shipment_code']}", show_alert=True
        )
    else:
        await callback.answer("Отправка отменена или не завершена.", show_alert=True)


@admin_router.message(Command("advance"))
async def start_shipment_advance(
    message: Message, command: CommandObject, state: FSMContext, pool
):
    try:
        code = normalize_shipment_code(command.args or "")
    except ValueError:
        await message.answer("Использование: /advance &lt;Shipment ID&gt;")
        return
    try:
        shipment = await shipment_repository.get_shipment_by_code(pool, code)
        if shipment is None:
            await message.answer(f"Shipment {escape(code)} не найден.")
            return
        to_status = next_shipment_status(str(shipment["status"]))
    except FinalShipmentStatusError:
        await message.answer(
            f"Shipment {escape(code)} уже прошёл таможню. "
            "Следующего статуса пока нет."
        )
        return
    except Exception:
        logger.exception("Failed to start shipment status advance")
        await message.answer("Не удалось загрузить Shipment. Попробуйте позже.")
        return

    await state.clear()
    await state.update_data(
        shipment=dict(shipment),
        shipment_code=code,
        from_status=str(shipment["status"]),
        to_status=to_status,
    )
    await state.set_state(ShipmentAdvanceForm.start_confirm)
    await message.answer(
        format_advance_candidate(shipment, to_status),
        reply_markup=shipment_advance_start_kb(code),
    )


@admin_router.callback_query(
    StateFilter(ShipmentAdvanceForm.start_confirm),
    F.data.startswith("shipment_advance_start:"),
)
async def confirm_shipment_advance_start(
    callback: CallbackQuery, state: FSMContext, pool
):
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Изменение статуса отменено. Данные не изменены.")
        await callback.answer()
        return
    data = await state.get_data()
    if action != data.get("shipment_code"):
        await callback.answer("Данные операции устарели.", show_alert=True)
        return
    try:
        shipment = await shipment_repository.get_shipment_by_code(pool, action)
        if shipment is None or shipment["status"] != data.get("from_status"):
            await state.clear()
            await callback.answer("Статус Shipment уже изменился.", show_alert=True)
            return
        if next_shipment_status(str(shipment["status"])) != data.get("to_status"):
            await state.clear()
            await callback.answer("Переход статуса больше недоступен.", show_alert=True)
            return
    except Exception:
        logger.exception("Failed to recheck shipment before advance")
        await callback.answer("Не удалось проверить Shipment.", show_alert=True)
        return
    await state.update_data(shipment=dict(shipment))
    await state.set_state(ShipmentAdvanceForm.note)
    await callback.message.edit_text(
        "Введите внутреннее примечание (2–500 символов) или /skip.\n"
        "Клиент это примечание не увидит."
    )
    await callback.answer()


@admin_router.message(Command("cancel"), StateFilter(ShipmentAdvanceForm))
async def cancel_shipment_advance(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Изменение статуса отменено. Данные не изменены.")


@admin_router.message(StateFilter(ShipmentAdvanceForm.note))
async def enter_shipment_event_note(message: Message, state: FSMContext):
    try:
        note = validate_event_note(message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ {escape(str(exc))}. Попробуйте ещё раз или /skip:")
        return
    await state.update_data(event_note=note)
    data = await state.get_data()
    await state.set_state(ShipmentAdvanceForm.confirm)
    await message.answer(
        format_advance_summary(data),
        reply_markup=shipment_advance_confirm_kb(data["shipment_code"]),
    )


@admin_router.callback_query(
    StateFilter(ShipmentAdvanceForm.confirm),
    F.data.startswith("shipment_advance_confirm:"),
)
async def shipment_advance_confirm_action(
    callback: CallbackQuery, state: FSMContext
):
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Изменение статуса отменено. Данные не изменены.")
        await callback.answer()
        return
    if action == "restart":
        await state.set_state(ShipmentAdvanceForm.note)
        await callback.message.edit_text("Введите примечание заново или /skip:")
        await callback.answer()


@admin_router.callback_query(
    StateFilter(ShipmentAdvanceForm.confirm),
    F.data.startswith("shipment_advance_accept:"),
)
async def apply_shipment_advance(
    callback: CallbackQuery, state: FSMContext, pool, bot: Bot
):
    data = await state.get_data()
    code = callback.data.split(":", 1)[1]
    if code != data.get("shipment_code"):
        await callback.answer("Данные операции устарели.", show_alert=True)
        return
    try:
        result = await shipment_repository.advance_shipment_status(
            pool,
            shipment_code=code,
            expected_from_status=data["from_status"],
            note=data.get("event_note"),
            created_by_telegram_id=callback.from_user.id,
        )
    except shipment_repository.ShipmentNotFoundError:
        await state.clear()
        await callback.answer("Shipment не найден.", show_alert=True)
        return
    except (shipment_repository.ShipmentStatusChangedError, FinalShipmentStatusError):
        await state.clear()
        await callback.answer("Статус Shipment уже изменился.", show_alert=True)
        return
    except Exception:
        logger.exception("Failed to advance shipment status transactionally")
        await callback.answer("Не удалось обновить статус. Попробуйте позже.", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_text(
        "✅ Статус Shipment обновлён.\n\n"
        f"Shipment ID: <code>{escape(code)}</code>\n"
        f"Статус: {shipment_status_label(str(result['event']['to_status']))}"
    )
    await callback.answer("Статус обновлён")
    if result["created"]:
        try:
            items = await shipment_repository.get_shipment_items(
                pool, result["shipment"]["id"]
            )
        except Exception:
            logger.exception(
                "Shipment advanced but notification items could not be loaded",
                extra={"shipment_id": result["shipment"]["id"]},
            )
            return
        for view in build_client_views(result["shipment"], items):
            try:
                await bot.send_message(
                    view["telegram_user_id"],
                    format_status_notification(view, result["event"]),
                )
            except Exception:
                logger.exception(
                    "Failed to notify one client about shipment status",
                    extra={"shipment_id": result["shipment"]["id"]},
                )


@admin_router.callback_query(F.data.startswith("shipment_advance_accept:"))
async def repeated_shipment_advance(callback: CallbackQuery, pool):
    code = callback.data.split(":", 1)[1]
    try:
        shipment = await shipment_repository.get_shipment_by_code(pool, code)
    except Exception:
        logger.exception("Failed to check repeated shipment advance callback")
        await callback.answer("Не удалось проверить Shipment.", show_alert=True)
        return
    if shipment is None:
        await callback.answer("Shipment не найден.", show_alert=True)
    else:
        await callback.answer(
            f"Текущий статус: {shipment_status_label(str(shipment['status']))}",
            show_alert=True,
        )


@admin_router.message(Command("shipments"))
async def list_shipments(message: Message, pool):
    try:
        rows = await shipment_repository.list_recent_shipments(pool, limit=20)
    except Exception:
        logger.exception("Failed to list shipments for admin")
        await message.answer("Не удалось загрузить отправления. Попробуйте позже.")
        return
    if not rows:
        await message.answer("Отправлений из Китая пока нет.")
        return
    await message.answer("🚛 <b>Последние отправления:</b>")
    for row in rows:
        await message.answer(format_admin_shipment(row))


@admin_router.message(Command("shipment"))
async def find_shipment(message: Message, command: CommandObject, pool):
    try:
        code = normalize_shipment_code(command.args or "")
    except ValueError:
        await message.answer("Использование: /shipment &lt;Shipment ID&gt;")
        return
    try:
        shipment = await shipment_repository.get_shipment_by_code(pool, code)
        items = (
            await shipment_repository.get_shipment_items(pool, shipment["id"])
            if shipment
            else []
        )
        events = (
            await shipment_repository.list_shipment_events(pool, shipment["id"])
            if shipment
            else []
        )
    except Exception:
        logger.exception("Failed to find shipment for admin")
        await message.answer("Не удалось загрузить отправление. Попробуйте позже.")
        return
    if shipment is None:
        await message.answer("Отправление не найдено.")
        return
    await message.answer(format_admin_shipment(shipment, details=items, events=events))


@router.message(StateFilter(None), F.text == "🚛 Мои отправления")
async def my_shipments(message: Message, state: FSMContext, pool):
    try:
        client = await require_registered_client(message, state, pool)
        if client is None:
            return
        rows = await shipment_repository.list_client_shipment_units(
            pool, message.from_user.id, limit=20
        )
        views = group_client_shipment_units(rows)
        for view in views:
            view["events"] = await shipment_repository.list_shipment_events(
                pool, view["id"]
            )
    except Exception:
        logger.exception("Failed to list client shipments")
        await message.answer("Не удалось загрузить отправления. Попробуйте позже.")
        return
    if not views:
        await message.answer("У вас пока нет грузов, отправленных из Китая.")
        return
    await message.answer("🚛 <b>Ваши отправления:</b>")
    for view in views:
        await message.answer(format_client_shipment(view))


router.include_router(admin_router)
