import re
from datetime import datetime
from decimal import Decimal
from html import escape
from typing import Any, Mapping, Sequence

from services.cargo_service import normalize_cargo_code


CONSOLIDATION_CODE_RE = re.compile(r"CS\d{6,}")
CONSOLIDATION_STATUS_LABELS = {
    "consolidated_china": "Консолидирован на китайском складе",
    "shipped_china": "Выехал из Китая",
    "in_transit": "В пути",
    "arrived_tajikistan": "Прибыл в Таджикистан",
    "customs_processing": "На таможенном оформлении",
    "customs_cleared": "Таможня пройдена",
    "assigned_pickup": "Назначен пункт выдачи",
    "domestic_transit": "Направлен в город получения",
    "arrived_pickup": "Прибыл в пункт выдачи",
    "ready_for_pickup": "Готов к получению",
}


def consolidation_status_label(status: str) -> str:
    return CONSOLIDATION_STATUS_LABELS.get(status, escape(status))


def format_consolidation_code(internal_id: int) -> str:
    if internal_id <= 0:
        raise ValueError("Внутренний ID консолидации должен быть положительным")
    return f"CS{internal_id:06d}"


def normalize_consolidation_code(value: str) -> str:
    code = value.strip().upper()
    if not CONSOLIDATION_CODE_RE.fullmatch(code):
        raise ValueError("Некорректный Consolidation ID")
    return code


def parse_cargo_codes(value: str) -> list[str]:
    raw_codes = value.replace(",", " ").split()
    codes: list[str] = []
    seen: set[str] = set()
    for raw_code in raw_codes:
        code = normalize_cargo_code(raw_code)
        if code not in seen:
            seen.add(code)
            codes.append(code)
    if not 2 <= len(codes) <= 50:
        raise ValueError("Укажите от 2 до 50 разных Cargo ID")
    return codes


def _decimal(value: Any, places: int) -> str:
    return f"{Decimal(str(value)):.{places}f}"


def _date(value: Any) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if isinstance(value, datetime) else "—"


def _codes(values: Sequence[Any]) -> str:
    return ", ".join(escape(str(value)) for value in values)


def format_consolidation_candidate(cargos: Sequence[Mapping[str, Any]]) -> str:
    first = cargos[0]
    total_weight = sum(Decimal(str(cargo["actual_weight_kg"])) for cargo in cargos)
    all_volumes_known = all(cargo.get("volume_m3") is not None for cargo in cargos)
    total_volume = (
        sum(Decimal(str(cargo["volume_m3"])) for cargo in cargos)
        if all_volumes_known
        else None
    )
    total_pieces = sum(int(cargo["pieces_count"]) for cargo in cargos)
    lines = [
        "🔗 <b>Начать консолидацию?</b>",
        "",
        f"Client ID: <code>{escape(str(first['client_code']))}</code>",
        f"Клиент: {escape(str(first['full_name']))}",
        f"Телефон: {escape(str(first['phone']))}",
        f"Город: {escape(str(first['delivery_city']))}",
        "",
        "<b>Выбранные Cargo:</b>",
    ]
    for cargo in cargos:
        volume = (
            f"{_decimal(cargo['volume_m3'], 4)} м³"
            if cargo.get("volume_m3") is not None
            else "не указан"
        )
        lines.append(
            f"• <code>{escape(str(cargo['cargo_code']))}</code> · "
            f"<code>{escape(str(cargo['tracking_number']))}</code> · "
            f"{_decimal(cargo['actual_weight_kg'], 3)} кг · {volume} · "
            f"мест: {cargo['pieces_count']}"
        )
    lines.extend(
        [
            "",
            f"Суммарный вес: {_decimal(total_weight, 3)} кг",
            (
                f"Суммарный объём: {_decimal(total_volume, 4)} м³"
                if total_volume is not None
                else "Суммарный объём: не определён полностью"
            ),
            f"Суммарное количество мест: {total_pieces}",
        ]
    )
    return "\n".join(lines)


def format_consolidation_summary(data: Mapping[str, Any]) -> str:
    volume = (
        f"{_decimal(data['final_volume_m3'], 4)} м³"
        if data.get("final_volume_m3") is not None
        else "не указан"
    )
    return (
        "📋 <b>Проверьте консолидацию</b>\n\n"
        "Consolidation ID: будет создан после подтверждения\n"
        f"Client ID: <code>{escape(str(data['client_code']))}</code>\n"
        f"Cargo: <code>{_codes(data['cargo_codes'])}</code>\n"
        f"Tracking Number: <code>{_codes(data['tracking_numbers'])}</code>\n"
        f"Описание: {escape(str(data.get('description') or 'не указано'))}\n"
        f"Итоговый вес: {_decimal(data['final_weight_kg'], 3)} кг\n"
        f"Итоговый объём: {volume}\n"
        f"Количество мест: {data['final_pieces_count']}\n"
        f"Фотографий: {len(data['photos'])}"
    )


def format_client_notification(consolidation: Mapping[str, Any]) -> str:
    volume = (
        f"{_decimal(consolidation['final_volume_m3'], 4)} м³"
        if consolidation.get("final_volume_m3") is not None
        else "не указан"
    )
    return (
        "✅ <b>Ваши грузы объединены на китайском складе.</b>\n\n"
        f"Consolidation ID: <code>{escape(str(consolidation['consolidation_code']))}</code>\n"
        f"Cargo: <code>{_codes(consolidation['cargo_codes'])}</code>\n"
        f"Tracking Number: <code>{_codes(consolidation['tracking_numbers'])}</code>\n"
        f"Итоговый вес: {_decimal(consolidation['final_weight_kg'], 3)} кг\n"
        f"Итоговый объём: {volume}\n"
        f"Количество мест: {consolidation['final_pieces_count']}\n"
        "Статус: Консолидирован на китайском складе"
    )


def format_client_consolidation(consolidation: Mapping[str, Any]) -> str:
    volume = (
        f"{_decimal(consolidation['final_volume_m3'], 4)} м³"
        if consolidation.get("final_volume_m3") is not None
        else "не указан"
    )
    lines = [
        f"🔗 <b>Консолидация <code>{escape(str(consolidation['consolidation_code']))}</code></b>",
        f"Cargo: <code>{_codes(consolidation['cargo_codes'])}</code>",
        f"Tracking Number: <code>{_codes(consolidation['tracking_numbers'])}</code>",
        f"Статус: {consolidation_status_label(str(consolidation.get('status', 'consolidated_china')))}",
        f"Итоговый вес: {_decimal(consolidation['final_weight_kg'], 3)} кг",
        f"Итоговый объём: {volume}",
        f"Количество мест: {consolidation['final_pieces_count']}",
    ]
    if consolidation.get("description"):
        lines.append(f"Описание: {escape(str(consolidation['description']))}")
    lines.extend(
        [
            f"Фотографий: {consolidation.get('photos_count', 0)}",
            f"Дата: {_date(consolidation.get('consolidated_at'))}",
        ]
    )
    return "\n".join(lines)


def format_admin_consolidation(
    consolidation: Mapping[str, Any],
    *,
    full: bool = False,
) -> str:
    lines = [
        f"🔗 Consolidation ID: <code>{escape(str(consolidation['consolidation_code']))}</code>",
        f"Client ID: <code>{escape(str(consolidation['client_code']))}</code>",
        f"Клиент: {escape(str(consolidation['full_name']))}",
        f"Cargo: <code>{_codes(consolidation['cargo_codes'])}</code>",
        f"Итоговый вес: {_decimal(consolidation['final_weight_kg'], 3)} кг",
        f"Количество мест: {consolidation['final_pieces_count']}",
        f"Дата: {_date(consolidation.get('consolidated_at'))}",
    ]
    if full:
        volume = (
            f"{_decimal(consolidation['final_volume_m3'], 4)} м³"
            if consolidation.get("final_volume_m3") is not None
            else "не указан"
        )
        lines.extend(
            [
                f"Телефон: {escape(str(consolidation['phone']))}",
                f"Город: {escape(str(consolidation['delivery_city']))}",
                f"Tracking Number: <code>{_codes(consolidation['tracking_numbers'])}</code>",
                f"Описание: {escape(str(consolidation.get('description') or 'не указано'))}",
                f"Итоговый объём: {volume}",
                f"Фотографий: {consolidation.get('photos_count', 0)}",
                f"Статус: {consolidation_status_label(str(consolidation.get('status', 'consolidated_china')))}",
            ]
        )
    return "\n".join(lines)
