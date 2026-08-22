import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from filters import IsAdmin
from keyboards import (
    handover_confirm_kb, handover_recipient_kb, handover_start_kb,
    payment_confirm_kb, payment_method_kb,
)
from repositories import completions as repository
from services.completion_service import (
    format_handover, format_handover_notification, format_handover_summary, format_payment,
    format_payment_notification, format_payment_summary, normalize_payment_code,
    parse_amount, validate_note, validate_payment_method,
    validate_recipient_name, validate_recipient_phone, validate_recipient_type,
    validate_reference,
)
from services.delivery_service import format_delivery, normalize_delivery_code
from states import HandoverForm, PaymentForm


router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())
logger = logging.getLogger(__name__)


@router.message(Command("cancel"), StateFilter(HandoverForm, PaymentForm))
async def cancel_completion(message: Message, state: FSMContext):
    await state.clear(); await message.answer("❌ Операция отменена. Данные не изменены.")


def _handover_error(exc: Exception, code: str) -> str:
    if isinstance(exc, repository.DeliveryNotFoundError): return f"Delivery {code} не найдена."
    if isinstance(exc, repository.DeliveryNotReadyError): return f"Delivery {code} ещё не готова к получению."
    if isinstance(exc, repository.HandoverAlreadyExistsError): return f"Delivery {code} уже выдана получателю."
    if isinstance(exc, repository.CompletionStatusError): return "Статус изменился. Обновите данные и повторите операцию."
    return "Не удалось оформить выдачу."


def _payment_error(exc: Exception, code: str) -> str:
    if isinstance(exc, repository.DeliveryNotFoundError): return f"Delivery {code} не найдена."
    if isinstance(exc, repository.HandoverRequiredError): return f"Сначала необходимо зафиксировать выдачу Delivery {code}."
    if isinstance(exc, repository.PaymentAlreadyExistsError): return f"Оплата Delivery {code} уже записана: {exc.code}."
    if isinstance(exc, repository.CompletionStatusError): return "Статус изменился. Обновите данные и повторите операцию."
    return "Не удалось зафиксировать оплату."


@router.message(Command("handover"))
async def handover_start(message: Message, command: CommandObject, state: FSMContext, pool):
    try: code = normalize_delivery_code(command.args or "")
    except ValueError: await message.answer("Использование: /handover DL000001"); return
    try: row = await repository.get_handover_candidate(pool, code)
    except Exception as exc:
        if not isinstance(exc, (repository.DeliveryNotFoundError, repository.DeliveryNotReadyError, repository.HandoverAlreadyExistsError)): logger.exception("Failed handover precheck")
        await message.answer(_handover_error(exc, code)); return
    await state.clear(); await state.update_data(delivery_code=code, delivery=dict(row))
    await state.set_state(HandoverForm.start_confirm)
    await message.answer(format_delivery(row, admin=True), reply_markup=handover_start_kb(code))


@router.callback_query(StateFilter(HandoverForm.start_confirm), F.data.startswith("handover_start:"))
async def handover_begin(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":", 1)[1]; data = await state.get_data()
    if action == "cancel": await state.clear(); await callback.message.edit_text("❌ Выдача отменена. Данные не изменены."); await callback.answer(); return
    if action != data.get("delivery_code"): await callback.answer("Данные устарели.", show_alert=True); return
    await state.set_state(HandoverForm.recipient_type)
    await callback.message.edit_text("Кто получает груз?", reply_markup=handover_recipient_kb()); await callback.answer()


@router.callback_query(StateFilter(HandoverForm.recipient_type), F.data.startswith("handover_recipient:"))
async def handover_recipient(callback: CallbackQuery, state: FSMContext):
    try: recipient_type = validate_recipient_type(callback.data.split(":", 1)[1])
    except ValueError: await callback.answer("Некорректный вариант.", show_alert=True); return
    data = await state.get_data(); await state.update_data(recipient_type=recipient_type)
    if recipient_type == "client":
        await state.update_data(recipient_name=data["delivery"]["full_name"])
        await state.set_state(HandoverForm.recipient_phone)
        await callback.message.edit_text("Введите телефон получателя или /skip:")
    else:
        await state.set_state(HandoverForm.recipient_name)
        await callback.message.edit_text("Введите имя представителя:")
    await callback.answer()


@router.message(StateFilter(HandoverForm.recipient_name))
async def handover_name(message: Message, state: FSMContext):
    try: value = validate_recipient_name(message.text or "")
    except ValueError as exc: await message.answer(f"❌ {escape(str(exc))}."); return
    await state.update_data(recipient_name=value); await state.set_state(HandoverForm.recipient_phone)
    await message.answer("Введите телефон получателя или /skip:")


@router.message(StateFilter(HandoverForm.recipient_phone))
async def handover_phone(message: Message, state: FSMContext):
    try: value = validate_recipient_phone(message.text or "")
    except ValueError as exc: await message.answer(f"❌ {escape(str(exc))}."); return
    await state.update_data(recipient_phone=value); await state.set_state(HandoverForm.note)
    await message.answer("Введите внутреннее примечание или /skip:")


@router.message(StateFilter(HandoverForm.note))
async def handover_note(message: Message, state: FSMContext):
    try: value = validate_note(message.text or "")
    except ValueError as exc: await message.answer(f"❌ {escape(str(exc))}."); return
    await state.update_data(handover_note=value); data = await state.get_data(); await state.set_state(HandoverForm.confirm)
    await message.answer(format_handover_summary(data), reply_markup=handover_confirm_kb(data["delivery_code"]))


@router.callback_query(StateFilter(HandoverForm.confirm), F.data.startswith("handover_accept:"))
async def handover_accept(callback: CallbackQuery, state: FSMContext, pool, bot: Bot):
    code = callback.data.split(":", 1)[1]; data = await state.get_data()
    if code == "cancel": await state.clear(); await callback.message.edit_text("❌ Выдача отменена. Данные не изменены."); await callback.answer(); return
    if code == "restart":
        await state.set_state(HandoverForm.recipient_type)
        await callback.message.edit_text("Кто получает груз?", reply_markup=handover_recipient_kb()); await callback.answer(); return
    if code != data.get("delivery_code"): await callback.answer("Данные устарели.", show_alert=True); return
    try:
        result = await repository.create_handover(pool, delivery_code=code, recipient_type=data["recipient_type"], recipient_name=data["recipient_name"], recipient_phone=data.get("recipient_phone"), note=data.get("handover_note"), actor_id=callback.from_user.id)
    except Exception as exc:
        if not isinstance(exc, (repository.DeliveryNotFoundError, repository.DeliveryNotReadyError, repository.CompletionStatusError)): logger.exception("Failed handover")
        await state.clear(); await callback.answer(_handover_error(exc, code), show_alert=True); return
    row = result["delivery"]; await state.clear()
    await callback.message.edit_text(f"✅ Выдача зафиксирована для <code>{code}</code>."); await callback.answer()
    if result["created"]:
        try: await bot.send_message(row["telegram_user_id"], format_handover_notification(row))
        except Exception: logger.exception("Failed handover notification", extra={"delivery_id": row["id"]})


@router.message(Command("record_payment"))
async def payment_start(message: Message, command: CommandObject, state: FSMContext, pool):
    try: code = normalize_delivery_code(command.args or "")
    except ValueError: await message.answer("Использование: /record_payment DL000001"); return
    try: candidate = await repository.get_payment_candidate(pool, code)
    except Exception as exc:
        if not isinstance(exc, (repository.DeliveryNotFoundError, repository.HandoverRequiredError, repository.PaymentAlreadyExistsError)): logger.exception("Failed payment precheck")
        await message.answer(_payment_error(exc, code)); return
    await state.clear(); await state.update_data(delivery_code=code, delivery=dict(candidate["delivery"]), handover=dict(candidate["handover"]))
    await state.set_state(PaymentForm.amount)
    h=candidate["handover"]
    await message.answer(format_delivery(candidate["delivery"], admin=True)+f"\n\n<b>Выдача:</b> {escape(str(h['recipient_name']))}\nВведите полученную сумму в TJS, например 250 или 250,50:")


@router.message(StateFilter(PaymentForm.amount))
async def payment_amount(message: Message, state: FSMContext):
    try: amount = parse_amount(message.text or "")
    except ValueError as exc: await message.answer(f"❌ {escape(str(exc))}."); return
    await state.update_data(amount=amount); await state.set_state(PaymentForm.method)
    await message.answer("Выберите способ оплаты:", reply_markup=payment_method_kb())


@router.callback_query(StateFilter(PaymentForm.method), F.data.startswith("payment_method:"))
async def payment_method(callback: CallbackQuery, state: FSMContext):
    try: method = validate_payment_method(callback.data.split(":", 1)[1])
    except ValueError: await callback.answer("Некорректный способ.", show_alert=True); return
    await state.update_data(payment_method=method); await state.set_state(PaymentForm.reference)
    await callback.message.edit_text("Введите номер квитанции/reference или /skip:"); await callback.answer()


@router.message(StateFilter(PaymentForm.reference))
async def payment_reference(message: Message, state: FSMContext):
    try: value = validate_reference(message.text or "")
    except ValueError as exc: await message.answer(f"❌ {escape(str(exc))}."); return
    await state.update_data(payment_reference=value); await state.set_state(PaymentForm.note)
    await message.answer("Введите внутреннее примечание или /skip:")


@router.message(StateFilter(PaymentForm.note))
async def payment_note(message: Message, state: FSMContext):
    try: value = validate_note(message.text or "")
    except ValueError as exc: await message.answer(f"❌ {escape(str(exc))}."); return
    await state.update_data(payment_note=value); data = await state.get_data(); await state.set_state(PaymentForm.confirm)
    await message.answer(format_payment_summary(data), reply_markup=payment_confirm_kb(data["delivery_code"]))


@router.callback_query(StateFilter(PaymentForm.confirm), F.data.startswith("payment_accept:"))
async def payment_accept(callback: CallbackQuery, state: FSMContext, pool, bot: Bot):
    code = callback.data.split(":", 1)[1]; data = await state.get_data()
    if code == "cancel": await state.clear(); await callback.message.edit_text("❌ Оплата отменена. Данные не изменены."); await callback.answer(); return
    if code == "restart":
        await state.set_state(PaymentForm.amount); await callback.message.edit_text("Введите сумму заново в TJS:"); await callback.answer(); return
    if code != data.get("delivery_code"): await callback.answer("Данные устарели.", show_alert=True); return
    try:
        result = await repository.create_payment(pool, delivery_code=code, amount=data["amount"], payment_method=data["payment_method"], reference=data.get("payment_reference"), note=data.get("payment_note"), actor_id=callback.from_user.id)
    except Exception as exc:
        if not isinstance(exc, (repository.DeliveryNotFoundError, repository.HandoverRequiredError, repository.PaymentAlreadyExistsError, repository.CompletionStatusError)): logger.exception("Failed payment")
        await state.clear(); await callback.answer(_payment_error(exc, code), show_alert=True); return
    row = result["payment"]; await state.clear()
    await callback.message.edit_text("✅ Оплата зафиксирована.\n\n" + format_payment(row, admin=True)); await callback.answer()
    if result["created"]:
        try: await bot.send_message(row["telegram_user_id"], format_payment_notification(row))
        except Exception: logger.exception("Failed payment notification", extra={"delivery_id": row["delivery_id"]})


@router.message(Command("handovers"))
async def handovers(message: Message, pool):
    rows = await repository.list_handovers(pool)
    if not rows: await message.answer("Выдач пока нет."); return
    for row in rows: await message.answer(format_handover(row, admin=True))


@router.message(Command("payments"))
async def payments(message: Message, pool):
    rows = await repository.list_payments(pool)
    if not rows: await message.answer("Оплат пока нет."); return
    for row in rows: await message.answer(format_payment(row, admin=True))


@router.message(Command("payment"))
async def payment_find(message: Message, command: CommandObject, pool):
    raw = command.args or ""
    try:
        code = normalize_payment_code(raw) if raw.strip().upper().startswith("PY") else normalize_delivery_code(raw)
    except ValueError: await message.answer("Использование: /payment PY000001 или /payment DL000001"); return
    row = await repository.get_payment(pool, code)
    await message.answer(format_payment(row, admin=True) if row else "Оплата не найдена.")


@router.callback_query(F.data.startswith("handover_accept:"))
async def repeated_handover(callback: CallbackQuery, pool):
    code=callback.data.split(":",1)[1]
    if code in {"cancel","restart"}: await callback.answer("Операция уже завершена или отменена.",show_alert=True); return
    try: await repository.get_handover_candidate(pool,code)
    except repository.HandoverAlreadyExistsError: await callback.answer(f"Delivery {code} уже выдана получателю.",show_alert=True); return
    except Exception: logger.exception("Failed repeated handover lookup")
    await callback.answer("Операция уже завершена или отменена.", show_alert=True)


@router.callback_query(F.data.startswith("payment_accept:"))
async def repeated_payment(callback: CallbackQuery, pool):
    code=callback.data.split(":",1)[1]
    if code in {"cancel","restart"}: await callback.answer("Операция уже завершена или отменена.",show_alert=True); return
    try:
        row=await repository.get_payment(pool,code)
        if row: await callback.answer(f"Оплата уже записана: {row['payment_code']}.",show_alert=True); return
    except Exception: logger.exception("Failed repeated payment lookup")
    await callback.answer("Операция уже завершена или отменена.", show_alert=True)
