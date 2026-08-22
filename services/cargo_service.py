import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any, Mapping, Optional, Sequence


STATUS_RECEIVED_CHINA = "received_china"
CARGO_CODE_RE = re.compile(r"CG\d{6,}")


def _parse_decimal(value: str, *, maximum: Decimal, decimal_places: int) -> Decimal:
    raw = value.strip().replace(",", ".")
    try:
        number = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Введите корректное число") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError("Значение должно быть больше нуля")
    if number > maximum:
        raise ValueError(f"Значение не должно превышать {maximum}")
    exponent = number.as_tuple().exponent
    if exponent < -decimal_places:
        raise ValueError(f"Допустимо не более {decimal_places} знаков после запятой")
    return number


def parse_weight(value: str) -> Decimal:
    return _parse_decimal(value, maximum=Decimal("999999"), decimal_places=3)


def parse_volume(value: str) -> Optional[Decimal]:
    if value.strip().lower() == "/skip":
        return None
    return _parse_decimal(value, maximum=Decimal("9999"), decimal_places=4)


def parse_pieces_count(value: str) -> int:
    raw = value.strip()
    if not raw.isdigit():
        raise ValueError("Введите целое число от 1 до 10000")
    count = int(raw)
    if not 1 <= count <= 10000:
        raise ValueError("Введите целое число от 1 до 10000")
    return count


def validate_description(value: str) -> Optional[str]:
    if value.strip().lower() == "/skip":
        return None
    description = " ".join(value.split())
    if not 2 <= len(description) <= 500:
        raise ValueError("Описание должно содержать от 2 до 500 символов")
    return description


def validate_photos(photos: Sequence[Mapping[str, str]]) -> None:
    if not 1 <= len(photos) <= 10:
        raise ValueError("Нужно добавить от 1 до 10 фотографий")
    unique_ids = {photo["file_unique_id"] for photo in photos}
    if len(unique_ids) != len(photos):
        raise ValueError("Одна и та же фотография добавлена несколько раз")


def format_cargo_code(internal_id: int) -> str:
    if internal_id <= 0:
        raise ValueError("Внутренний ID груза должен быть положительным")
    return f"CG{internal_id:06d}"


def normalize_cargo_code(value: str) -> str:
    code = value.strip().upper()
    if not CARGO_CODE_RE.fullmatch(code):
        raise ValueError("Некорректный Cargo ID")
    return code


def _date(value: Any) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if isinstance(value, datetime) else "—"


def _decimal(value: Any, places: int) -> str:
    return f"{Decimal(str(value)):.{places}f}"


def format_receipt_candidate(tracking: Mapping[str, Any]) -> str:
    return (
        "📦 <b>Начать складскую приёмку?</b>\n\n"
        f"Tracking Number: <code>{escape(str(tracking['tracking_number']))}</code>\n"
        f"Client ID: <code>{escape(str(tracking['client_code']))}</code>\n"
        f"Клиент: {escape(str(tracking['full_name']))}\n"
        f"Телефон: {escape(str(tracking['phone']))}\n"
        f"Город получения: {escape(str(tracking['delivery_city']))}\n"
        f"Добавлен: {_date(tracking.get('created_at'))}"
    )


def format_receipt_summary(data: Mapping[str, Any]) -> str:
    description = data.get("description") or "не указано"
    volume = (
        f"{_decimal(data['volume_m3'], 4)} м³"
        if data.get("volume_m3") is not None
        else "не указан"
    )
    return (
        "📋 <b>Проверьте данные приёмки</b>\n\n"
        f"Tracking Number: <code>{escape(str(data['tracking_number']))}</code>\n"
        f"Client ID: <code>{escape(str(data['client_code']))}</code>\n"
        f"Описание: {escape(str(description))}\n"
        f"Фактический вес: {_decimal(data['actual_weight_kg'], 3)} кг\n"
        f"Объём: {volume}\n"
        f"Количество мест: {data['pieces_count']}\n"
        f"Фотографий: {len(data['photos'])}"
    )


def format_client_notification(cargo: Mapping[str, Any]) -> str:
    volume = (
        f"{_decimal(cargo['volume_m3'], 4)} м³"
        if cargo.get("volume_m3") is not None
        else "не указан"
    )
    return (
        "✅ <b>Ваш груз принят на китайском складе.</b>\n\n"
        f"Cargo ID: <code>{escape(str(cargo['cargo_code']))}</code>\n"
        f"Tracking Number: <code>{escape(str(cargo['tracking_number']))}</code>\n"
        f"Вес: {_decimal(cargo['actual_weight_kg'], 3)} кг\n"
        f"Объём: {volume}\n"
        f"Количество мест: {cargo['pieces_count']}\n"
        "Статус: Принят на китайском складе"
    )


def format_client_cargo(cargo: Mapping[str, Any]) -> str:
    description = cargo.get("description")
    volume = (
        f"{_decimal(cargo['volume_m3'], 4)} м³"
        if cargo.get("volume_m3") is not None
        else "не указан"
    )
    lines = [
        f"🚚 <b>Cargo <code>{escape(str(cargo['cargo_code']))}</code></b>",
        f"Tracking Number: <code>{escape(str(cargo['tracking_number']))}</code>",
        "Статус: Принят на китайском складе",
        f"Фактический вес: {_decimal(cargo['actual_weight_kg'], 3)} кг",
        f"Объём: {volume}",
        f"Количество мест: {cargo['pieces_count']}",
    ]
    if description:
        lines.append(f"Описание: {escape(str(description))}")
    lines.extend(
        [
            f"Фотографий: {cargo.get('photos_count', 0)}",
            f"Принят: {_date(cargo.get('received_at'))}",
        ]
    )
    return "\n".join(lines)


def format_admin_cargo(cargo: Mapping[str, Any], *, full: bool = False) -> str:
    lines = [
        f"📦 Cargo ID: <code>{escape(str(cargo['cargo_code']))}</code>",
        f"Tracking Number: <code>{escape(str(cargo['tracking_number']))}</code>",
        f"Client ID: <code>{escape(str(cargo['client_code']))}</code>",
        f"Клиент: {escape(str(cargo['full_name']))}",
        f"Вес: {_decimal(cargo['actual_weight_kg'], 3)} кг",
        f"Количество мест: {cargo['pieces_count']}",
        f"Принят: {_date(cargo.get('received_at'))}",
    ]
    if full:
        volume = (
            f"{_decimal(cargo['volume_m3'], 4)} м³"
            if cargo.get("volume_m3") is not None
            else "не указан"
        )
        lines.extend(
            [
                f"Телефон: {escape(str(cargo['phone']))}",
                f"Город: {escape(str(cargo['delivery_city']))}",
                f"Описание: {escape(str(cargo.get('description') or 'не указано'))}",
                f"Объём: {volume}",
                f"Фотографий: {cargo.get('photos_count', 0)}",
                "Статус: Принят на китайском складе",
            ]
        )
    return "\n".join(lines)
