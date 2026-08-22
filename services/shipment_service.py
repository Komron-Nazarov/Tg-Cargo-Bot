import re
from datetime import datetime
from decimal import Decimal
from html import escape
from typing import Any, Mapping, Sequence

from services.cargo_service import normalize_cargo_code
from services.consolidation_service import normalize_consolidation_code


SHIPMENT_CODE_RE = re.compile(r"SH\d{6,}")
TRANSPORT_LABELS = {
    "truck": "🚛 Автомобиль",
    "air": "✈️ Авиа",
    "rail": "🚆 Железная дорога",
    "other": "📦 Другое",
}


def format_shipment_code(internal_id: int) -> str:
    if internal_id <= 0:
        raise ValueError("Внутренний ID отправки должен быть положительным")
    return f"SH{internal_id:06d}"


def normalize_shipment_code(value: str) -> str:
    code = value.strip().upper()
    if not SHIPMENT_CODE_RE.fullmatch(code):
        raise ValueError("Некорректный Shipment ID")
    return code


def parse_dispatch_codes(value: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in value.replace(",", " ").split():
        upper = raw.strip().upper()
        if upper.startswith("CG"):
            code = normalize_cargo_code(upper)
        elif upper.startswith("CS"):
            code = normalize_consolidation_code(upper)
        else:
            raise ValueError(f"Неизвестный ID: {raw}")
        if code not in seen:
            seen.add(code)
            result.append(code)
    if not 1 <= len(result) <= 200:
        raise ValueError("Укажите от 1 до 200 разных Cargo или Consolidation ID")
    return result


def validate_transport_type(value: str) -> str:
    if value not in TRANSPORT_LABELS:
        raise ValueError("Некорректный тип транспорта")
    return value


def validate_optional_text(value: str, *, maximum: int, label: str) -> str | None:
    if value.strip().lower() == "/skip":
        return None
    text = " ".join(value.split())
    if not 2 <= len(text) <= maximum:
        raise ValueError(f"{label} должен содержать от 2 до {maximum} символов")
    return text


def validate_reference(value: str) -> str | None:
    return validate_optional_text(value, maximum=100, label="Reference")


def validate_note(value: str) -> str | None:
    return validate_optional_text(value, maximum=500, label="Примечание")


def transport_label(value: str) -> str:
    return TRANSPORT_LABELS.get(value, escape(value))


def _decimal(value: Any, places: int) -> str:
    return f"{Decimal(str(value)):.{places}f}"


def _date(value: Any) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if isinstance(value, datetime) else "—"


def shipment_totals(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    weight = sum(Decimal(str(item["weight_kg"])) for item in items)
    volume = (
        sum(Decimal(str(item["volume_m3"])) for item in items)
        if all(item.get("volume_m3") is not None for item in items)
        else None
    )
    return {
        "weight_kg": weight,
        "volume_m3": volume,
        "pieces_count": sum(int(item["pieces_count"]) for item in items),
    }


def _codes(items: Sequence[Mapping[str, Any]], item_type: str) -> list[str]:
    return [str(item["public_code"]) for item in items if item["item_type"] == item_type]


def _tracking_numbers(items: Sequence[Mapping[str, Any]]) -> list[str]:
    result: list[str] = []
    for item in items:
        result.extend(str(value) for value in item.get("tracking_numbers", []))
    return result


def _line(label: str, values: Sequence[str]) -> str:
    return f"{label}: <code>{escape(', '.join(values))}</code>" if values else f"{label}: —"


def format_dispatch_candidate(items: Sequence[Mapping[str, Any]]) -> str:
    totals = shipment_totals(items)
    clients = sorted({str(item["client_code"]) for item in items})
    volume = (
        f"{_decimal(totals['volume_m3'], 4)} м³"
        if totals["volume_m3"] is not None
        else "не определён полностью"
    )
    return "\n".join(
        [
            "🚛 <b>Подтвердите состав отправки</b>",
            "",
            _line("Cargo", _codes(items, "cargo")),
            _line("Consolidation", _codes(items, "consolidation")),
            _line("Tracking Number", _tracking_numbers(items)),
            f"Клиентов: {len(clients)}",
            _line("Client ID", clients),
            f"Общий вес: {_decimal(totals['weight_kg'], 3)} кг",
            f"Общий объём: {volume}",
            f"Количество мест: {totals['pieces_count']}",
            f"Транспортных единиц: {len(items)}",
        ]
    )


def format_dispatch_summary(data: Mapping[str, Any]) -> str:
    items = data["items"]
    totals = shipment_totals(items)
    volume = (
        f"{_decimal(totals['volume_m3'], 4)} м³"
        if totals["volume_m3"] is not None
        else "не определён полностью"
    )
    return "\n".join(
        [
            "📋 <b>Проверьте отправку</b>",
            "",
            "Shipment ID: будет создан после подтверждения",
            _line("Cargo", _codes(items, "cargo")),
            _line("Consolidation", _codes(items, "consolidation")),
            _line("Tracking Number", _tracking_numbers(items)),
            f"Клиентов: {len({item['client_id'] for item in items})}",
            f"Общий вес: {_decimal(totals['weight_kg'], 3)} кг",
            f"Общий объём: {volume}",
            f"Количество мест: {totals['pieces_count']}",
            f"Транспорт: {transport_label(str(data['transport_type']))}",
            f"Reference: {escape(str(data.get('transport_reference') or 'не указан'))}",
            f"Примечание: {escape(str(data.get('note') or 'не указано'))}",
        ]
    )


def format_client_shipment(view: Mapping[str, Any], *, notification: bool = False) -> str:
    title = "✅ <b>Ваш груз выехал из Китая.</b>" if notification else "🚛 <b>Отправление</b>"
    volume = (
        f"{_decimal(view['client_volume_m3'], 4)} м³"
        if view.get("client_volume_m3") is not None
        else "не определён полностью"
    )
    return "\n".join(
        [
            title,
            "",
            f"Shipment ID: <code>{escape(str(view['shipment_code']))}</code>",
            _line("Cargo", list(view.get("cargo_codes", []))),
            _line("Consolidation", list(view.get("consolidation_codes", []))),
            _line("Tracking Number", list(view.get("tracking_numbers", []))),
            f"Вес ваших грузов: {_decimal(view['client_weight_kg'], 3)} кг",
            f"Объём ваших грузов: {volume}",
            f"Количество мест: {view['client_pieces_count']}",
            f"Транспорт: {transport_label(str(view['transport_type']))}",
            f"Reference: {escape(str(view.get('transport_reference') or 'не указан'))}",
            f"Дата выезда: {_date(view.get('departed_at'))}",
            "Статус: Выехал из Китая",
        ]
    )


def format_admin_shipment(shipment: Mapping[str, Any], *, details=None) -> str:
    lines = [
        f"🚛 Shipment ID: <code>{escape(str(shipment['shipment_code']))}</code>",
        f"Транспорт: {transport_label(str(shipment['transport_type']))}",
        f"Reference: {escape(str(shipment.get('transport_reference') or 'не указан'))}",
        f"Items: {shipment.get('items_count', len(details or []))}",
        f"Клиентов: {shipment.get('clients_count', len({x['client_id'] for x in (details or [])}))}",
        f"Дата выезда: {_date(shipment.get('departed_at'))}",
        "Статус: Выехал из Китая",
    ]
    if details:
        lines.append("")
        lines.append("<b>Состав:</b>")
        for item in details:
            item_label = "Cargo" if item["item_type"] == "cargo" else "Consolidation"
            trackings = ", ".join(str(value) for value in item.get("tracking_numbers", []))
            lines.append(
                f"• {item_label} <code>{escape(str(item['public_code']))}</code> · "
                f"Client ID <code>{escape(str(item['client_code']))}</code> · "
                f"{escape(str(item['full_name']))} · "
                f"Tracking <code>{escape(trackings)}</code> · "
                f"{_decimal(item['weight_kg'], 3)} кг · мест: {item['pieces_count']}"
            )
    return "\n".join(lines)


def build_client_views(
    shipment: Mapping[str, Any], items: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    grouped: dict[int, list[Mapping[str, Any]]] = {}
    for item in items:
        grouped.setdefault(int(item["telegram_user_id"]), []).append(item)
    views = []
    for telegram_user_id, client_items in grouped.items():
        totals = shipment_totals(client_items)
        views.append(
            {
                **dict(shipment),
                "telegram_user_id": telegram_user_id,
                "cargo_codes": _codes(client_items, "cargo"),
                "consolidation_codes": _codes(client_items, "consolidation"),
                "tracking_numbers": _tracking_numbers(client_items),
                "client_weight_kg": totals["weight_kg"],
                "client_volume_m3": totals["volume_m3"],
                "client_pieces_count": totals["pieces_count"],
            }
        )
    return views


def group_client_shipment_units(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    shipments: dict[int, dict[str, Any]] = {}
    for row in rows:
        shipment_id = int(row["id"])
        entry = shipments.setdefault(shipment_id, {**dict(row), "_items": []})
        entry["_items"].append(row)
    result = []
    for entry in shipments.values():
        items = entry.pop("_items")
        result.extend(build_client_views(entry, items))
    return result
