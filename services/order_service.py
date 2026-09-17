import math


def normalize_order_name(value: str) -> str:
    name = " ".join(value.split())
    if not 2 <= len(name) <= 120:
        raise ValueError("Название должно содержать от 2 до 120 символов")
    return name


def normalize_order_country(value: str) -> str:
    country = " ".join(value.split())
    if not 2 <= len(country) <= 100:
        raise ValueError("Страна должна содержать от 2 до 100 символов")
    return country


def parse_order_weight(value: str) -> float:
    try:
        weight = float(value.strip().replace(",", "."))
    except ValueError as exc:
        raise ValueError("Введите корректный вес") from exc
    if not math.isfinite(weight) or not 0 < weight <= 999999:
        raise ValueError("Вес должен быть больше нуля и не превышать 999999 кг")
    return weight
