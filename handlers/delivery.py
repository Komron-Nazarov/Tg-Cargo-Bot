import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from filters import IsAdmin
from handlers.client import require_registered_client
from keyboards import (
    delivery_advance_confirm_kb, delivery_advance_start_kb, delivery_assign_kb,
    pickup_city_kb, pickup_confirm_kb,
)
from repositories import deliveries as delivery_repository
from repositories import pickup_points as pickup_repository
from services.delivery_service import (
    FinalDeliveryStatusError, delivery_status_label, format_assignment_candidate,
    format_delivery, format_delivery_notification, next_delivery_status,
    normalize_delivery_code, validate_event_note,
)
from services.pickup_service import (
    format_pickup, normalize_pickup_code, validate_city, validate_pickup_address,
    validate_pickup_name, validate_pickup_note, validate_pickup_phone,
)
from services.shipment_service import normalize_shipment_code
from services.tracking_service import normalize_client_code
from states import DeliveryAdvanceForm, DeliveryAssignForm, PickupPointForm


router = Router()
admin_router = Router()
admin_router.message.filter(IsAdmin())
admin_router.callback_query.filter(IsAdmin())
logger = logging.getLogger(__name__)


@admin_router.message(Command("pickup_add"))
async def pickup_add(message: Message, state: FSMContext):
    await state.clear(); await state.set_state(PickupPointForm.city)
    await message.answer("Выберите город пункта выдачи:", reply_markup=pickup_city_kb())


@admin_router.callback_query(StateFilter(PickupPointForm.city), F.data.startswith("pickup_city:"))
async def pickup_city(callback: CallbackQuery, state: FSMContext):
    try: city = validate_city(callback.data.split(":",1)[1])
    except ValueError:
        await callback.answer("Некорректный город.", show_alert=True); return
    await state.update_data(city=city); await state.set_state(PickupPointForm.name)
    await callback.message.edit_text("Введите название пункта (2–100 символов):"); await callback.answer()


@admin_router.message(StateFilter(PickupPointForm.name))
async def pickup_name(message: Message, state: FSMContext):
    try: value=validate_pickup_name(message.text or "")
    except ValueError as exc: await message.answer(f"❌ {escape(str(exc))}."); return
    await state.update_data(name=value); await state.set_state(PickupPointForm.address)
    await message.answer("Введите адрес пункта (5–300 символов):")


@admin_router.message(StateFilter(PickupPointForm.address))
async def pickup_address(message: Message, state: FSMContext):
    try: value=validate_pickup_address(message.text or "")
    except ValueError as exc: await message.answer(f"❌ {escape(str(exc))}."); return
    await state.update_data(address=value); await state.set_state(PickupPointForm.phone)
    await message.answer("Введите телефон пункта или /skip:")


@admin_router.message(StateFilter(PickupPointForm.phone))
async def pickup_phone(message: Message, state: FSMContext):
    try: value=validate_pickup_phone(message.text or "")
    except ValueError as exc: await message.answer(f"❌ {escape(str(exc))}."); return
    await state.update_data(phone=value); await state.set_state(PickupPointForm.note)
    await message.answer("Введите внутреннее примечание или /skip:")


@admin_router.message(StateFilter(PickupPointForm.note))
async def pickup_note(message: Message, state: FSMContext):
    try: value=validate_pickup_note(message.text or "")
    except ValueError as exc: await message.answer(f"❌ {escape(str(exc))}."); return
    await state.update_data(note=value); data=await state.get_data(); await state.set_state(PickupPointForm.confirm)
    await message.answer(format_pickup(data,preview=True),reply_markup=pickup_confirm_kb())


@admin_router.message(Command("cancel"), StateFilter(PickupPointForm, DeliveryAssignForm, DeliveryAdvanceForm))
async def cancel_delivery_flow(message: Message, state: FSMContext):
    await state.clear(); await message.answer("❌ Операция отменена. Данные не изменены.")


@admin_router.callback_query(StateFilter(PickupPointForm.confirm), F.data.startswith("pickup_accept:"))
async def pickup_accept(callback: CallbackQuery, state: FSMContext, pool):
    action=callback.data.split(":",1)[1]
    if action=="cancel": await state.clear(); await callback.message.edit_text("❌ Создание отменено."); await callback.answer(); return
    data=await state.get_data()
    try:
        row=await pickup_repository.create_pickup_point(pool,city=data["city"],name=data["name"],address=data["address"],phone=data.get("phone"),note=data.get("note"),created_by_telegram_id=callback.from_user.id)
    except Exception: logger.exception("Failed to create pickup point"); await callback.answer("Не удалось создать пункт.",show_alert=True); return
    await state.clear(); await callback.message.edit_text("✅ Пункт выдачи создан.\n\n"+format_pickup(row)); await callback.answer()


@admin_router.callback_query(F.data=="pickup_accept:create")
async def repeated_pickup(callback: CallbackQuery):
    await callback.answer("Операция уже завершена или отменена.",show_alert=True)


@admin_router.message(Command("pickups"))
async def pickups(message: Message,pool):
    try: rows=await pickup_repository.list_active_pickup_points(pool)
    except Exception: logger.exception("Failed to list pickups"); await message.answer("Не удалось загрузить пункты."); return
    if not rows: await message.answer("Пункты выдачи ещё не настроены."); return
    for row in rows: await message.answer(format_pickup(row))


@admin_router.message(Command("pickup"))
async def pickup_find(message: Message,command: CommandObject,pool):
    try: code=normalize_pickup_code(command.args or "")
    except ValueError: await message.answer("Использование: /pickup &lt;Pickup Point ID&gt;"); return
    row=await pickup_repository.get_pickup_point_by_code(pool,code)
    await message.answer(format_pickup(row) if row else "Пункт выдачи не найден.")


def _assignment_error(exc, sh, client, pickup):
    if isinstance(exc,delivery_repository.ShipmentNotFoundError): return f"Shipment {sh} не найден."
    if isinstance(exc,delivery_repository.ShipmentNotClearedError): return f"Shipment {sh} ещё не прошёл таможню."
    if isinstance(exc,delivery_repository.ClientNotFoundError): return f"Client ID {client} не найден."
    if isinstance(exc,delivery_repository.ClientNotInShipmentError): return f"Клиент {client} не имеет грузов в Shipment {sh}."
    if isinstance(exc,delivery_repository.PickupUnavailableError): return f"Pickup Point {pickup} не найден или неактивен."
    if isinstance(exc,delivery_repository.DeliveryAlreadyExistsError): return f"Для клиента {client} в Shipment {sh} доставка уже создана: {exc.code}."
    return "Не удалось проверить назначение."


@admin_router.message(Command("assign"))
async def assign(message: Message,command: CommandObject,state:FSMContext,pool):
    parts=(command.args or "").split()
    try:
        if len(parts)!=3: raise ValueError
        sh=normalize_shipment_code(parts[0]); client=normalize_client_code(parts[1]); pickup=normalize_pickup_code(parts[2])
    except ValueError: await message.answer("Использование: /assign SH000001 C000001 PP000001"); return
    try: data=await delivery_repository.get_assignment_candidate(pool,sh,client,pickup)
    except Exception as exc:
        if not isinstance(exc,(delivery_repository.ShipmentNotFoundError,delivery_repository.ShipmentNotClearedError,delivery_repository.ClientNotFoundError,delivery_repository.ClientNotInShipmentError,delivery_repository.PickupUnavailableError,delivery_repository.DeliveryAlreadyExistsError)): logger.exception("Failed assignment precheck")
        await message.answer(_assignment_error(exc,sh,client,pickup)); return
    await state.clear(); await state.update_data(shipment_code=sh,client_code=client,pickup_code=pickup)
    await state.set_state(DeliveryAssignForm.confirm)
    await message.answer(format_assignment_candidate(data),reply_markup=delivery_assign_kb(sh))


@admin_router.callback_query(StateFilter(DeliveryAssignForm.confirm),F.data.startswith("delivery_assign:"))
async def assign_confirm(callback:CallbackQuery,state:FSMContext,pool,bot:Bot):
    action=callback.data.split(":",1)[1]
    if action=="cancel": await state.clear(); await callback.message.edit_text("❌ Назначение отменено."); await callback.answer(); return
    data=await state.get_data()
    if action!=data.get("shipment_code"): await callback.answer("Данные устарели.",show_alert=True); return
    try: row=await delivery_repository.create_delivery(pool,shipment_code=data["shipment_code"],client_code=data["client_code"],pickup_code=data["pickup_code"],actor_id=callback.from_user.id)
    except Exception as exc: await state.clear(); await callback.answer(_assignment_error(exc,data["shipment_code"],data["client_code"],data["pickup_code"]),show_alert=True); return
    await state.clear(); await callback.message.edit_text(f"✅ Доставка создана: <code>{row['delivery_code']}</code>"); await callback.answer()
    try: await bot.send_message(row["telegram_user_id"],format_delivery_notification(row))
    except Exception: logger.exception("Failed delivery assignment notification",extra={"delivery_id":row["id"]})


@admin_router.message(Command("advance_delivery"))
async def advance_start(message:Message,command:CommandObject,state:FSMContext,pool):
    try: code=normalize_delivery_code(command.args or "")
    except ValueError: await message.answer("Использование: /advance_delivery DL000001"); return
    row=await delivery_repository.get_delivery_by_code(pool,code)
    if not row: await message.answer("Delivery не найдена."); return
    try: next_status=next_delivery_status(row["status"])
    except FinalDeliveryStatusError: await message.answer("Delivery уже готова к получению, выдана или завершена. Используйте отдельную команду /handover для выдачи."); return
    await state.clear(); await state.update_data(delivery_code=code,from_status=row["status"],to_status=next_status,delivery=dict(row)); await state.set_state(DeliveryAdvanceForm.start_confirm)
    await message.answer(format_delivery(row)+f"\n\nСледующий статус: {delivery_status_label(next_status)}",reply_markup=delivery_advance_start_kb(code))


@admin_router.callback_query(StateFilter(DeliveryAdvanceForm.start_confirm),F.data.startswith("delivery_advance_start:"))
async def advance_begin(callback:CallbackQuery,state:FSMContext):
    action=callback.data.split(":",1)[1]; data=await state.get_data()
    if action=="cancel": await state.clear(); await callback.message.edit_text("❌ Изменение отменено."); await callback.answer(); return
    if action!=data.get("delivery_code"): await callback.answer("Данные устарели.",show_alert=True); return
    await state.set_state(DeliveryAdvanceForm.note); await callback.message.edit_text("Введите внутреннее примечание или /skip:"); await callback.answer()


@admin_router.message(StateFilter(DeliveryAdvanceForm.note))
async def advance_note(message:Message,state:FSMContext):
    try: note=validate_event_note(message.text or "")
    except ValueError as exc: await message.answer(f"❌ {escape(str(exc))}."); return
    await state.update_data(event_note=note); data=await state.get_data(); await state.set_state(DeliveryAdvanceForm.confirm)
    await message.answer(format_delivery(data["delivery"])+f"\n\nНовый статус: {delivery_status_label(data['to_status'])}\nПримечание: {escape(str(note or 'не указано'))}",reply_markup=delivery_advance_confirm_kb(data["delivery_code"]))


@admin_router.callback_query(StateFilter(DeliveryAdvanceForm.confirm),F.data.startswith("delivery_advance_confirm:"))
async def advance_action(callback:CallbackQuery,state:FSMContext):
    action=callback.data.split(":",1)[1]
    if action=="cancel": await state.clear(); await callback.message.edit_text("❌ Изменение отменено."); await callback.answer(); return
    if action=="restart": await state.set_state(DeliveryAdvanceForm.note); await callback.message.edit_text("Введите примечание заново или /skip:"); await callback.answer()


@admin_router.callback_query(StateFilter(DeliveryAdvanceForm.confirm),F.data.startswith("delivery_advance_accept:"))
async def advance_accept(callback:CallbackQuery,state:FSMContext,pool,bot:Bot):
    data=await state.get_data(); code=callback.data.split(":",1)[1]
    if code!=data.get("delivery_code"): await callback.answer("Данные устарели.",show_alert=True); return
    try: result=await delivery_repository.advance_delivery(pool,delivery_code=code,expected_from_status=data["from_status"],note=data.get("event_note"),actor_id=callback.from_user.id)
    except Exception: logger.exception("Failed delivery advance"); await state.clear(); await callback.answer("Не удалось изменить статус.",show_alert=True); return
    row=result["delivery"]; await state.clear(); await callback.message.edit_text(f"✅ Delivery <code>{code}</code>\nСтатус: {delivery_status_label(row['status'])}"); await callback.answer()
    if result["created"]:
        try: await bot.send_message(row["telegram_user_id"],format_delivery_notification(row))
        except Exception: logger.exception("Failed delivery status notification",extra={"delivery_id":row["id"]})


@admin_router.message(Command("deliveries"))
async def deliveries(message:Message,pool):
    rows=await delivery_repository.list_deliveries(pool)
    if not rows: await message.answer("Доставок пока нет."); return
    for row in rows: await message.answer(format_delivery(row,admin=True))


@admin_router.message(Command("delivery"))
async def delivery_find(message:Message,command:CommandObject,pool):
    try: code=normalize_delivery_code(command.args or "")
    except ValueError: await message.answer("Использование: /delivery DL000001"); return
    row=await delivery_repository.get_delivery_by_code(pool,code)
    if not row: await message.answer("Delivery не найдена."); return
    events=await delivery_repository.list_delivery_events(pool,row["id"]); await message.answer(format_delivery(row,events,admin=True))


@router.message(StateFilter(None),F.text=="📍 Моя доставка")
async def my_delivery(message:Message,state:FSMContext,pool):
    if await require_registered_client(message,state,pool) is None: return
    rows=await delivery_repository.list_deliveries(pool,telegram_user_id=message.from_user.id)
    if not rows: await message.answer("У вас пока нет грузов, направленных в пункт выдачи."); return
    for row in rows:
        events=await delivery_repository.list_delivery_events(pool,row["id"]); await message.answer(format_delivery(row,events))


@admin_router.callback_query(F.data.startswith("delivery_assign:"))
async def repeated_assignment(callback: CallbackQuery):
    await callback.answer("Операция уже завершена или отменена.", show_alert=True)


@admin_router.callback_query(F.data.startswith("delivery_advance_accept:"))
async def repeated_delivery_advance(callback: CallbackQuery, pool):
    code = callback.data.split(":", 1)[1]
    try:
        row = await delivery_repository.get_delivery_by_code(pool, code)
    except Exception:
        logger.exception("Failed to check repeated delivery callback")
        await callback.answer("Не удалось проверить Delivery.", show_alert=True)
        return
    await callback.answer(
        f"Текущий статус: {delivery_status_label(row['status'])}" if row else "Delivery не найдена.",
        show_alert=True,
    )


router.include_router(admin_router)
