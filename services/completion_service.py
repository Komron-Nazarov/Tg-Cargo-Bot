import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any, Mapping


PAYMENT_CODE_RE=re.compile(r"PY\d{6,}")
RECIPIENT_TYPES={"client":"Сам клиент","representative":"Представитель"}
PAYMENT_METHODS={"cash":"Наличные","bank_transfer":"Банковский перевод","other":"Другое"}


def format_payment_code(value:int)->str:
    if value<=0: raise ValueError("ID должен быть положительным")
    return f"PY{value:06d}"


def normalize_payment_code(value:str)->str:
    code=value.strip().upper()
    if not PAYMENT_CODE_RE.fullmatch(code): raise ValueError("Некорректный Payment ID")
    return code


def validate_recipient_type(value:str)->str:
    if value not in RECIPIENT_TYPES: raise ValueError("Некорректный тип получателя")
    return value


def _text(value,min_len,max_len,label):
    result=" ".join(value.split())
    if not min_len<=len(result)<=max_len: raise ValueError(f"{label}: от {min_len} до {max_len} символов")
    return result


def validate_recipient_name(value:str)->str: return _text(value,2,150,"Имя")


def validate_optional(value:str,min_len:int,max_len:int,label:str)->str|None:
    if value.strip().lower()=="/skip": return None
    return _text(value,min_len,max_len,label)


def validate_recipient_phone(value:str)->str|None: return validate_optional(value,5,30,"Телефон")
def validate_note(value:str)->str|None: return validate_optional(value,2,500,"Примечание")
def validate_reference(value:str)->str|None: return validate_optional(value,2,100,"Reference")


def parse_amount(value:str)->Decimal:
    try: amount=Decimal(value.strip().replace(",","."))
    except InvalidOperation as exc: raise ValueError("Введите корректную сумму") from exc
    if not amount.is_finite() or amount<=0: raise ValueError("Сумма должна быть больше нуля")
    if amount>Decimal("999999999999.99"): raise ValueError("Сумма слишком большая")
    if amount.as_tuple().exponent < -2: raise ValueError("Допустимо не более двух знаков после запятой")
    return amount.quantize(Decimal("0.01"))


def validate_payment_method(value:str)->str:
    if value not in PAYMENT_METHODS: raise ValueError("Некорректный способ оплаты")
    return value


def _date(value:Any)->str: return value.strftime("%d.%m.%Y %H:%M") if isinstance(value,datetime) else "—"


def format_handover_summary(data:Mapping[str,Any])->str:
    d=data["delivery"]
    return "\n".join(["📦 <b>Подтвердите выдачу</b>","",
        f"Delivery ID: <code>{escape(str(d['delivery_code']))}</code>",f"Shipment ID: <code>{escape(str(d['shipment_code']))}</code>",
        f"Client ID: <code>{escape(str(d['client_code']))}</code>",f"Клиент: {escape(str(d['full_name']))} · {escape(str(d['client_phone']))}",
        f"Cargo: <code>{escape(', '.join(d.get('cargo_codes',[])))}</code>",f"Consolidation: <code>{escape(', '.join(d.get('consolidation_codes',[])))}</code>",
        f"Tracking: <code>{escape(', '.join(d.get('tracking_numbers',[])))}</code>",f"Пункт: <code>{escape(str(d['pickup_code']))}</code> · {escape(str(d['pickup_name']))}",
        f"Адрес: {escape(str(d['pickup_address']))}",f"Получатель: {RECIPIENT_TYPES[data['recipient_type']]}",
        f"Имя: {escape(str(data['recipient_name']))}",f"Телефон: {escape(str(data.get('recipient_phone') or 'не указан'))}",
        f"Примечание: {escape(str(data.get('handover_note') or 'не указано'))}"])


def format_payment_summary(data:Mapping[str,Any])->str:
    d=data["delivery"]
    h=data["handover"]
    return "\n".join(["💳 <b>Подтвердите оплату</b>","",f"Payment ID: будет создан после подтверждения",
        f"Delivery ID: <code>{escape(str(d['delivery_code']))}</code>",f"Shipment ID: <code>{escape(str(d['shipment_code']))}</code>",
        f"Client ID: <code>{escape(str(d['client_code']))}</code>",
        f"Выдано: {RECIPIENT_TYPES.get(str(h['recipient_type']), escape(str(h['recipient_type'])))} · {escape(str(h['recipient_name']))}",
        f"Дата выдачи: {_date(h.get('handed_over_at'))}",f"Сумма: {data['amount']:.2f} TJS",
        f"Способ: {PAYMENT_METHODS[data['payment_method']]}",f"Reference: {escape(str(data.get('payment_reference') or 'не указан'))}",
        f"Примечание: {escape(str(data.get('payment_note') or 'не указано'))}"])


def format_handover_notification(row):
    return f"✅ <b>Ваш груз выдан получателю.</b>\n\nDelivery ID: <code>{escape(str(row['delivery_code']))}</code>\nShipment ID: <code>{escape(str(row['shipment_code']))}</code>\nСтатус: Выдан получателю\nДата: {_date(row.get('handed_over_at'))}"


def format_handover(row, *, admin=False):
    lines = [
        f"📦 Delivery ID: <code>{escape(str(row['delivery_code']))}</code>",
        f"Client ID: <code>{escape(str(row['client_code']))}</code>",
        f"Получатель: {escape(str(row['recipient_name']))}",
        f"Тип: {RECIPIENT_TYPES.get(str(row['recipient_type']), escape(str(row['recipient_type'])))}",
        f"Телефон: {escape(str(row.get('recipient_phone') or 'не указан'))}",
        f"Выдан: {_date(row.get('handed_over_at'))}",
    ]
    if admin:
        lines.extend([
            f"Клиент: {escape(str(row['full_name']))}",
            f"Пункт: <code>{escape(str(row['pickup_code']))}</code> · {escape(str(row['pickup_name']))}",
            f"Примечание: {escape(str(row.get('note') or 'не указано'))}",
            f"Выдал: <code>{row['handed_over_by_telegram_id']}</code>",
        ])
    return "\n".join(lines)


def format_payment(row,*,admin=False):
    lines=[f"💳 Payment ID: <code>{escape(str(row['payment_code']))}</code>",f"Delivery ID: <code>{escape(str(row['delivery_code']))}</code>",
           f"Shipment ID: <code>{escape(str(row['shipment_code']))}</code>",f"Client ID: <code>{escape(str(row['client_code']))}</code>",f"Сумма: {Decimal(str(row['amount'])):.2f} TJS",
           f"Способ оплаты: {PAYMENT_METHODS.get(str(row['payment_method']),escape(str(row['payment_method'])))}",f"Reference: {escape(str(row.get('reference') or 'не указан'))}",f"Дата: {_date(row.get('paid_at'))}"]
    if admin: lines.extend([f"Клиент: {escape(str(row['full_name']))}",f"Примечание: {escape(str(row.get('note') or 'не указано'))}",f"Записал: <code>{row['recorded_by_telegram_id']}</code>"])
    return "\n".join(lines)


def format_payment_notification(row):
    return "✅ <b>Доставка завершена.</b>\n\n"+format_payment(row)+"\nСтатус: Доставка завершена"
