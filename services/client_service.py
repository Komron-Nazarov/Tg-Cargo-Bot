import re
from datetime import datetime
from html import escape
from typing import Any, Mapping, Optional


PHONE_SEPARATORS_RE = re.compile(r"[\s()\-.]")


def normalize_phone(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("Введите номер телефона")

    normalized = PHONE_SEPARATORS_RE.sub("", raw)
    if normalized.startswith("00"):
        normalized = "+" + normalized[2:]

    if normalized.startswith("+"):
        digits = normalized[1:]
        result = normalized
    else:
        digits = normalized
        result = normalized

    if not digits.isdigit() or not 7 <= len(digits) <= 15:
        raise ValueError("Введите корректный номер телефона")
    return result


def format_client_code(internal_id: int) -> str:
    if internal_id <= 0:
        raise ValueError("Внутренний ID клиента должен быть положительным")
    return f"C{internal_id:06d}"


def format_profile(client: Mapping[str, Any]) -> str:
    lines = [
        "👤 <b>Мой профиль</b>",
        "",
        f"Client ID: <code>{escape(str(client['client_code']))}</code>",
        f"Имя: {escape(str(client['full_name']))}",
        f"Телефон: {escape(str(client['phone']))}",
        f"Город получения: {escape(str(client['delivery_city']))}",
    ]
    created_at = client.get("created_at")
    if isinstance(created_at, datetime):
        lines.append(f"Дата регистрации: {created_at:%d.%m.%Y}")
    return "\n".join(lines)


def format_warehouse_address(
    client_code: str,
    address: Optional[str],
    recipient: Optional[str] = None,
    phone: Optional[str] = None,
) -> str:
    if not address or not address.strip():
        return "Адрес склада пока не настроен. Обратитесь к администратору."

    lines = ["🏭 <b>Адрес склада в Китае</b>", ""]
    if recipient and recipient.strip():
        lines.append(f"Получатель: {escape(recipient.strip())}")
    lines.append(f"Адрес: {escape(address.strip())}")
    if phone and phone.strip():
        lines.append(f"Телефон: {escape(phone.strip())}")
    lines.extend(
        [
            f"Client ID: <code>{escape(client_code)}</code>",
            "",
            "Обязательно укажите Client ID на посылке или в данных получателя.",
        ]
    )
    return "\n".join(lines)
