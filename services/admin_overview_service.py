from html import escape
from typing import Any, Mapping, Sequence

from repositories.orders import STATUS_LABELS as ORDER_STATUS_LABELS
from services.cargo_service import cargo_status_label
from services.tracking_service import status_label as tracking_status_label


def format_client_overview(
    client: Mapping[str, Any],
    trackings: Sequence[Mapping[str, Any]],
    cargos: Sequence[Mapping[str, Any]],
    orders: Sequence[Mapping[str, Any]],
) -> str:
    code = escape(str(client["client_code"]))
    username = client.get("telegram_username")
    telegram = f"@{escape(str(username))}" if username else str(client["telegram_user_id"])
    lines = [
        f"👤 <b>Клиент <code>{code}</code></b>",
        f"Имя: {escape(str(client['full_name']))}",
        f"Телефон: {escape(str(client['phone']))}",
        f"Город: {escape(str(client['delivery_city']))}",
        f"Telegram: {telegram}",
        f"Активен: {'да' if client['is_active'] else 'нет'}",
        "",
        "🔎 <b>Последние трек-номера</b>",
    ]
    lines.extend(
        f"<code>{escape(str(row['tracking_number']))}</code> — "
        f"{tracking_status_label(str(row['status']))}"
        for row in trackings
    )
    if not trackings:
        lines.append("Нет")
    lines.extend(["", "📦 <b>Последние грузы</b>"])
    lines.extend(
        f"<code>{escape(str(row['cargo_code']))}</code> — "
        f"{cargo_status_label(str(row['status']))}"
        for row in cargos
    )
    if not cargos:
        lines.append("Нет")
    lines.extend(["", "📝 <b>Последние запросы</b>"])
    lines.extend(
        f"№{row['id']} · {escape(str(row['name']))} — "
        f"{ORDER_STATUS_LABELS.get(str(row['status']), escape(str(row['status'])))}"
        for row in orders
    )
    if not orders:
        lines.append("Нет")
    lines.extend(
        [
            "",
            f"Все треки: /tracking {code}",
            f"Все грузы: /client_cargos {code}",
        ]
    )
    return "\n".join(lines)


def format_admin_order(order: Mapping[str, Any]) -> str:
    lines = [
        f"📝 <b>Запрос №{order['id']}</b>",
        f"Товар: {escape(str(order['name']))}",
        f"Вес: {escape(str(order['weight']))} кг",
        f"Страна: {escape(str(order['country']))}",
        f"Статус: {ORDER_STATUS_LABELS.get(str(order['status']), escape(str(order['status'])))}",
    ]
    if order.get("client_code"):
        code = escape(str(order["client_code"]))
        lines.extend(
            [
                f"Клиент: {escape(str(order['full_name']))} · <code>{code}</code>",
                f"Телефон: {escape(str(order['phone']))}",
                f"Город: {escape(str(order['delivery_city']))}",
                f"Карточка клиента: /client {code}",
            ]
        )
    else:
        lines.append("Клиент не зарегистрирован в боте")
    username = order.get("username")
    lines.append(
        f"Telegram: @{escape(str(username))}" if username else f"Telegram ID: {order['user_id']}"
    )
    return "\n".join(lines)
