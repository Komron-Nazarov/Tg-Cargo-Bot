"""Weight-only estimate. This is not an invoice or a recorded payment."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def parse_estimate_weight(value: str) -> Decimal:
    raw = value.strip().replace(",", ".")
    try:
        weight = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Введите вес числом, например 2,5") from exc
    if not weight.is_finite() or not 0 < weight <= Decimal("999999"):
        raise ValueError("Вес должен быть больше нуля и не превышать 999999 кг")
    if weight.as_tuple().exponent < -3:
        raise ValueError("Укажите не более 3 знаков после запятой")
    return weight


def estimate_usd(weight_kg: Decimal, price_per_kg_usd: Decimal) -> Decimal:
    if not weight_kg.is_finite() or weight_kg <= 0:
        raise ValueError("Вес должен быть положительным")
    if not price_per_kg_usd.is_finite() or price_per_kg_usd <= 0:
        raise ValueError("Тариф должен быть положительным")
    return (weight_kg * price_per_kg_usd).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_estimate(weight_kg: Decimal, price_per_kg_usd: Decimal) -> str:
    total = estimate_usd(weight_kg, price_per_kg_usd)
    weight_label = format(weight_kg.normalize(), "f")
    rate_label = f"{price_per_kg_usd:.2f}"
    return (
        "🧮 <b>Предварительный расчёт доставки</b>\n\n"
        f"Вес: {weight_label} кг\n"
        f"Тариф: ${rate_label} за кг\n"
        f"Ориентировочно: <b>${total:.2f}</b>\n\n"
        "Это расчёт только по весу, не счёт к оплате. Фактический вес после приёмки "
        "и возможные дополнительные услуги подтверждает компания. "
        "Оплата фиксируется администратором отдельно."
    )
