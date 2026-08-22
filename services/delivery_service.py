import re
from datetime import datetime
from decimal import Decimal
from html import escape
from typing import Any, Mapping, Sequence

from services.pickup_service import city_label


DELIVERY_CODE_RE = re.compile(r"DL\d{6,}")
DELIVERY_STATUSES = ("assigned_pickup", "domestic_transit", "arrived_pickup", "ready_for_pickup")
STATUS_LABELS = {
    "assigned_pickup": "Назначен пункт выдачи",
    "domestic_transit": "Направлен в город получения",
    "arrived_pickup": "Прибыл в пункт выдачи",
    "ready_for_pickup": "Готов к получению",
    "handed_over": "Выдан получателю",
    "completed": "Доставка завершена",
}


class FinalDeliveryStatusError(ValueError): pass
class InvalidDeliveryTransitionError(ValueError): pass


def format_delivery_code(internal_id: int) -> str:
    if internal_id <= 0: raise ValueError("ID должен быть положительным")
    return f"DL{internal_id:06d}"


def normalize_delivery_code(value: str) -> str:
    code = value.strip().upper()
    if not DELIVERY_CODE_RE.fullmatch(code): raise ValueError("Некорректный Delivery ID")
    return code


def delivery_status_label(status: str) -> str: return STATUS_LABELS.get(status, escape(status))


def next_delivery_status(status: str) -> str:
    if status in {"handed_over", "completed"}: raise FinalDeliveryStatusError("Delivery уже выдана или завершена")
    if status not in DELIVERY_STATUSES: raise InvalidDeliveryTransitionError("Неизвестный статус Delivery")
    pos = DELIVERY_STATUSES.index(status)
    if pos == len(DELIVERY_STATUSES) - 1: raise FinalDeliveryStatusError("Delivery уже готова к получению")
    return DELIVERY_STATUSES[pos + 1]


def validate_event_note(value: str) -> str | None:
    if value.strip().lower() == "/skip": return None
    note = " ".join(value.split())
    if not 2 <= len(note) <= 500: raise ValueError("Примечание должно содержать от 2 до 500 символов")
    return note


def _date(value: Any) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if isinstance(value, datetime) else "—"


def _codes(values: Sequence[Any]) -> str:
    return escape(", ".join(str(x) for x in values)) if values else "—"


def format_assignment_candidate(data: Mapping[str, Any]) -> str:
    return "\n".join([
        "📍 <b>Назначение пункта выдачи</b>", "",
        f"Shipment ID: <code>{escape(str(data['shipment_code']))}</code>",
        f"Client ID: <code>{escape(str(data['client_code']))}</code>",
        f"Клиент: {escape(str(data['full_name']))}",
        f"Телефон: {escape(str(data['client_phone']))}",
        f"Город регистрации: {escape(str(data['delivery_city']))}",
        f"Cargo: <code>{_codes(data.get('cargo_codes', []))}</code>",
        f"Consolidation: <code>{_codes(data.get('consolidation_codes', []))}</code>",
        f"Tracking Number: <code>{_codes(data.get('tracking_numbers', []))}</code>",
        f"Вес: {Decimal(str(data['weight_kg'])):.3f} кг",
        f"Количество мест: {data['pieces_count']}", "",
        f"Pickup Point ID: <code>{escape(str(data['pickup_code']))}</code>",
        f"Город: {city_label(str(data['pickup_city']))}",
        f"Пункт: {escape(str(data['pickup_name']))}",
        f"Адрес: {escape(str(data['pickup_address']))}",
        f"Телефон пункта: {escape(str(data.get('pickup_phone') or 'не указан'))}",
    ])


def format_delivery(delivery: Mapping[str, Any], events=(), *, admin=False) -> str:
    lines = [
        f"📍 Delivery ID: <code>{escape(str(delivery['delivery_code']))}</code>",
        f"Shipment ID: <code>{escape(str(delivery['shipment_code']))}</code>",
        f"Client ID: <code>{escape(str(delivery['client_code']))}</code>",
        f"Cargo: <code>{_codes(delivery.get('cargo_codes', []))}</code>",
        f"Consolidation: <code>{_codes(delivery.get('consolidation_codes', []))}</code>",
        f"Tracking Number: <code>{_codes(delivery.get('tracking_numbers', []))}</code>",
        f"Статус: {delivery_status_label(str(delivery['status']))}",
        f"Город: {city_label(str(delivery['pickup_city']))}",
        f"Pickup Point ID: <code>{escape(str(delivery['pickup_code']))}</code>",
        f"Пункт: {escape(str(delivery['pickup_name']))}",
        f"Адрес: {escape(str(delivery['pickup_address']))}",
        f"Телефон пункта: {escape(str(delivery.get('pickup_phone') or 'не указан'))}",
        f"Назначен: {_date(delivery.get('assigned_at'))}",
        f"Готов: {_date(delivery.get('ready_at'))}",
    ]
    if delivery.get("handed_over_at"):
        lines.append(f"Выдан: {_date(delivery.get('handed_over_at'))}")
    if delivery.get("payment_code"):
        payment_labels = {"cash": "Наличные", "bank_transfer": "Банковский перевод", "other": "Другое"}
        lines.extend([
            f"Payment ID: <code>{escape(str(delivery['payment_code']))}</code>",
            f"Оплата: {Decimal(str(delivery['payment_amount'])):.2f} TJS",
            f"Способ оплаты: {payment_labels.get(str(delivery.get('payment_method')), escape(str(delivery.get('payment_method'))))}",
            f"Оплачено: {_date(delivery.get('paid_at'))}",
        ])
    if admin:
        lines.insert(3, f"Клиент: {escape(str(delivery['full_name']))} · {escape(str(delivery['client_phone']))}")
    lines.extend(["", "<b>История:</b>", f"✅ {_date(delivery.get('assigned_at'))} — Назначен пункт выдачи"])
    for event in events:
        line = f"✅ {_date(event.get('occurred_at'))} — {delivery_status_label(str(event['to_status']))}"
        if admin:
            line += f" · админ: <code>{event['created_by_telegram_id']}</code>"
            if event.get("note"): line += f" · {escape(str(event['note']))}"
        lines.append(line)
    if delivery.get("handed_over_at"):
        lines.append(f"✅ {_date(delivery.get('handed_over_at'))} — Выдан получателю")
    if delivery.get("paid_at"):
        lines.append(f"✅ {_date(delivery.get('paid_at'))} — Оплата зафиксирована, доставка завершена")
    return "\n".join(lines)


def format_delivery_notification(delivery: Mapping[str, Any]) -> str:
    status = str(delivery["status"])
    titles = {
        "assigned_pickup": "Вашему грузу назначен пункт выдачи.",
        "domestic_transit": f"Ваш груз направлен в {city_label(str(delivery['pickup_city']))}.",
        "arrived_pickup": "Ваш груз прибыл в пункт выдачи.",
        "ready_for_pickup": "Ваш груз готов к получению.",
    }
    return "\n".join([
        f"✅ <b>{titles[status]}</b>", "",
        f"Delivery ID: <code>{escape(str(delivery['delivery_code']))}</code>",
        f"Shipment ID: <code>{escape(str(delivery['shipment_code']))}</code>",
        f"Cargo: <code>{_codes(delivery.get('cargo_codes', []))}</code>",
        f"Consolidation: <code>{_codes(delivery.get('consolidation_codes', []))}</code>",
        f"Tracking Number: <code>{_codes(delivery.get('tracking_numbers', []))}</code>",
        f"Город: {city_label(str(delivery['pickup_city']))}",
        f"Пункт: {escape(str(delivery['pickup_name']))}",
        f"Адрес: {escape(str(delivery['pickup_address']))}",
        f"Телефон: {escape(str(delivery.get('pickup_phone') or 'не указан'))}",
        f"Статус: {delivery_status_label(status)}",
    ])
