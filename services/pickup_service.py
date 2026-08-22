import re
from html import escape
from typing import Any, Mapping


PICKUP_CODE_RE = re.compile(r"PP\d{6,}")
CITIES = {"dushanbe": "Душанбе", "khujand": "Худжанд"}


def format_pickup_code(internal_id: int) -> str:
    if internal_id <= 0: raise ValueError("ID должен быть положительным")
    return f"PP{internal_id:06d}"


def normalize_pickup_code(value: str) -> str:
    code = value.strip().upper()
    if not PICKUP_CODE_RE.fullmatch(code): raise ValueError("Некорректный Pickup Point ID")
    return code


def validate_city(value: str) -> str:
    if value not in CITIES: raise ValueError("Поддерживаются только Душанбе и Худжанд")
    return value


def _text(value: str, minimum: int, maximum: int, label: str) -> str:
    result = " ".join(value.split())
    if not minimum <= len(result) <= maximum:
        raise ValueError(f"{label}: от {minimum} до {maximum} символов")
    return result


def validate_pickup_name(value: str) -> str: return _text(value, 2, 100, "Название")
def validate_pickup_address(value: str) -> str: return _text(value, 5, 300, "Адрес")


def validate_optional(value: str, minimum: int, maximum: int, label: str) -> str | None:
    if value.strip().lower() == "/skip": return None
    return _text(value, minimum, maximum, label)


def validate_pickup_phone(value: str) -> str | None:
    return validate_optional(value, 5, 30, "Телефон")


def validate_pickup_note(value: str) -> str | None:
    return validate_optional(value, 2, 500, "Примечание")


def city_label(city: str) -> str: return CITIES.get(city, escape(city))


def format_pickup(data: Mapping[str, Any], *, preview=False) -> str:
    code = "будет создан после подтверждения" if preview else escape(str(data["pickup_code"]))
    return "\n".join([
        "📍 <b>Пункт выдачи</b>", "",
        f"Pickup Point ID: <code>{code}</code>",
        f"Город: {city_label(str(data['city']))}",
        f"Название: {escape(str(data['name']))}",
        f"Адрес: {escape(str(data['address']))}",
        f"Телефон: {escape(str(data.get('phone') or 'не указан'))}",
        f"Примечание: {escape(str(data.get('note') or 'не указано'))}",
        f"Статус: {'Активен' if data.get('is_active', True) else 'Неактивен'}",
    ])
