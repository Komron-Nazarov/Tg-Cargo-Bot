from datetime import datetime
from html import escape
from typing import Any, Mapping, Sequence


SHIPMENT_STATUSES = (
    "departed_china",
    "in_transit",
    "arrived_tajikistan",
    "customs_processing",
    "customs_cleared",
)

STATUS_LABELS = {
    "departed_china": "Выехал из Китая",
    "in_transit": "В пути",
    "arrived_tajikistan": "Прибыл в Таджикистан",
    "customs_processing": "На таможенном оформлении",
    "customs_cleared": "Таможня пройдена",
}
TRANSPORT_LABELS = {
    "truck": "🚛 Автомобиль",
    "air": "✈️ Авиа",
    "rail": "🚆 Железная дорога",
    "other": "📦 Другое",
}


class FinalShipmentStatusError(ValueError):
    pass


class InvalidShipmentTransitionError(ValueError):
    pass


def shipment_status_label(status: str) -> str:
    return STATUS_LABELS.get(status, escape(status))


def next_shipment_status(current_status: str) -> str:
    if current_status not in SHIPMENT_STATUSES:
        raise InvalidShipmentTransitionError("Неизвестный статус Shipment")
    position = SHIPMENT_STATUSES.index(current_status)
    if position == len(SHIPMENT_STATUSES) - 1:
        raise FinalShipmentStatusError("Shipment уже прошёл таможню")
    return SHIPMENT_STATUSES[position + 1]


def validate_shipment_transition(from_status: str, to_status: str) -> None:
    if next_shipment_status(from_status) != to_status:
        raise InvalidShipmentTransitionError("Разрешён только следующий статус Shipment")


def validate_event_note(value: str) -> str | None:
    if value.strip().lower() == "/skip":
        return None
    note = " ".join(value.split())
    if not 2 <= len(note) <= 500:
        raise ValueError("Примечание должно содержать от 2 до 500 символов")
    return note


def _date(value: Any) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if isinstance(value, datetime) else "—"


def format_advance_candidate(shipment: Mapping[str, Any], next_status: str) -> str:
    return "\n".join(
        [
            "🚛 <b>Изменение статуса Shipment</b>",
            "",
            f"Shipment ID: <code>{escape(str(shipment['shipment_code']))}</code>",
            f"Текущий статус: {shipment_status_label(str(shipment['status']))}",
            f"Следующий статус: {shipment_status_label(next_status)}",
            f"Транспорт: {TRANSPORT_LABELS.get(str(shipment['transport_type']), escape(str(shipment['transport_type'])))}",
            f"Reference: {escape(str(shipment.get('transport_reference') or 'не указан'))}",
            f"Дата выезда: {_date(shipment.get('departed_at'))}",
            f"Items: {shipment.get('items_count', 0)}",
            f"Клиентов: {shipment.get('clients_count', 0)}",
        ]
    )


def format_advance_summary(data: Mapping[str, Any]) -> str:
    shipment = data["shipment"]
    return "\n".join(
        [
            "📋 <b>Подтвердите новый статус</b>",
            "",
            f"Shipment ID: <code>{escape(str(shipment['shipment_code']))}</code>",
            f"Текущий статус: {shipment_status_label(str(data['from_status']))}",
            f"Новый статус: {shipment_status_label(str(data['to_status']))}",
            f"Транспорт: {TRANSPORT_LABELS.get(str(shipment['transport_type']), escape(str(shipment['transport_type'])))}",
            f"Reference: {escape(str(shipment.get('transport_reference') or 'не указан'))}",
            f"Дата выезда: {_date(shipment.get('departed_at'))}",
            f"Примечание: {escape(str(data.get('event_note') or 'не указано'))}",
            f"Items: {shipment.get('items_count', 0)}",
            f"Клиентов: {shipment.get('clients_count', 0)}",
        ]
    )


def format_shipment_history(
    shipment: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    *,
    admin: bool = False,
) -> str:
    lines = ["<b>История:</b>", f"✅ {_date(shipment.get('departed_at'))} — Выехал из Китая"]
    for event in events:
        line = (
            f"✅ {_date(event.get('occurred_at'))} — "
            f"{shipment_status_label(str(event['to_status']))}"
        )
        if admin:
            line += f" · админ: <code>{event['created_by_telegram_id']}</code>"
            if event.get("note"):
                line += f" · {escape(str(event['note']))}"
        lines.append(line)
    return "\n".join(lines)


def format_status_notification(
    view: Mapping[str, Any], event: Mapping[str, Any]
) -> str:
    titles = {
        "in_transit": "Статус вашего отправления обновлён.",
        "arrived_tajikistan": "Ваш груз прибыл в Таджикистан.",
        "customs_processing": "Ваш груз проходит таможенное оформление.",
        "customs_cleared": "Таможенное оформление завершено.",
    }
    def codes(name: str) -> str:
        values = view.get(name, [])
        return escape(", ".join(str(value) for value in values)) if values else "—"

    status = str(event["to_status"])
    return "\n".join(
        [
            f"✅ <b>{titles.get(status, 'Статус отправления обновлён.')}</b>",
            "",
            f"Shipment ID: <code>{escape(str(view['shipment_code']))}</code>",
            f"Cargo: <code>{codes('cargo_codes')}</code>",
            f"Consolidation: <code>{codes('consolidation_codes')}</code>",
            f"Tracking Number: <code>{codes('tracking_numbers')}</code>",
            f"Новый статус: {shipment_status_label(status)}",
            f"Дата: {_date(event.get('occurred_at'))}",
        ]
    )
