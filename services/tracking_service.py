import re
from datetime import datetime
from html import escape
from typing import Any, Mapping


STATUS_DECLARED = "declared"
STATUS_CANCELLED = "cancelled"

STATUS_LABELS = {
    STATUS_DECLARED: "⏳ Ожидается на складе",
    STATUS_CANCELLED: "❌ Отменён",
}

TRACKING_RE = re.compile(r"(?=.*[A-Z0-9])[A-Z0-9-]{5,64}")
CLIENT_CODE_RE = re.compile(r"C\d{6,}")


def normalize_tracking_number(value: str) -> str:
    normalized = value.strip().replace(" ", "").upper()
    if not TRACKING_RE.fullmatch(normalized):
        raise ValueError(
            "Трек-номер должен содержать 5–64 латинские буквы, цифры или дефис"
        )
    return normalized


def normalize_client_code(value: str) -> str:
    normalized = value.strip().upper()
    if not CLIENT_CODE_RE.fullmatch(normalized):
        raise ValueError("Некорректный Client ID")
    return normalized


def is_client_code(value: str) -> bool:
    return CLIENT_CODE_RE.fullmatch(value.strip().upper()) is not None


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, escape(status))


def _format_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    return "—"


def format_client_tracking(tracking: Mapping[str, Any]) -> str:
    return (
        f"🔎 <code>{escape(str(tracking['tracking_number']))}</code>\n"
        f"Статус: {status_label(str(tracking['status']))}\n"
        f"Добавлен: {_format_date(tracking.get('created_at'))}"
    )


def format_admin_tracking(tracking: Mapping[str, Any]) -> str:
    return (
        f"🔎 <code>{escape(str(tracking['tracking_number']))}</code>\n"
        f"Client ID: <code>{escape(str(tracking['client_code']))}</code>\n"
        f"Клиент: {escape(str(tracking['full_name']))}\n"
        f"Статус: {status_label(str(tracking['status']))}\n"
        f"Добавлен: {_format_date(tracking.get('created_at'))}"
    )


def format_admin_notification(
    client: Mapping[str, Any],
    tracking_number: str,
) -> str:
    username = client.get("telegram_username")
    telegram_identity = (
        f"@{escape(str(username))}"
        if username
        else str(client["telegram_user_id"])
    )
    return (
        "📦 <b>Новый китайский трек-номер</b>\n\n"
        f"Client ID: <code>{escape(str(client['client_code']))}</code>\n"
        f"Клиент: {escape(str(client['full_name']))}\n"
        f"Telegram: {telegram_identity}\n"
        f"Трек-номер: <code>{escape(tracking_number)}</code>\n"
        f"Статус: {status_label(STATUS_DECLARED)}"
    )


def duplicate_message(existing_client_id: int, current_client_id: int) -> str:
    if existing_client_id == current_client_id:
        return "Этот трек-номер уже есть в вашем списке."
    return (
        "Этот трек-номер уже зарегистрирован. "
        "Если это ошибка, обратитесь к администратору."
    )
