"""Stateless, read-only training journey. Callback payloads contain demo choices only."""

from dataclasses import dataclass, replace
from decimal import Decimal

from services.pricing_service import estimate_usd

PRODUCTS = {"s": "кроссовки", "c": "одежда", "e": "электроника"}
WEIGHTS = {"a": Decimal("0.5"), "b": Decimal("2.5"), "c": Decimal("5")}
CITIES = {"d": "Душанбе", "h": "Худжанд"}
LAST_STEP = 14


@dataclass(frozen=True)
class DemoState:
    step: int = 0
    product: str = "-"
    weight: str = "-"
    consolidated: str = "-"
    city: str = "-"

    def encode(self) -> str:
        return f"demo:{self.step}:{self.product}:{self.weight}:{self.consolidated}:{self.city}"

    @classmethod
    def decode(cls, value: str) -> "DemoState":
        parts = value.split(":")
        if len(parts) != 6 or parts[0] != "demo" or not parts[1].isascii() or not parts[1].isdecimal():
            raise ValueError("Некорректный шаг обучения")
        state = cls(int(parts[1]), *parts[2:])
        if not 0 <= state.step <= LAST_STEP:
            raise ValueError("Некорректный шаг обучения")
        if state.product not in {*PRODUCTS, "-"} or state.weight not in {*WEIGHTS, "-"}:
            raise ValueError("Некорректный выбор")
        if state.consolidated not in {"-", "y", "n"} or state.city not in {*CITIES, "-"}:
            raise ValueError("Некорректный выбор")
        if state.step >= 1 and state.product == "-":
            raise ValueError("Сначала выберите товар")
        if state.step >= 2 and state.weight == "-":
            raise ValueError("Сначала выберите вес")
        if state.step >= 8 and state.consolidated == "-":
            raise ValueError("Сначала выберите консолидацию")
        if state.step >= 12 and state.city == "-":
            raise ValueError("Сначала выберите город")
        return state

    def next(self, **choices: str) -> "DemoState":
        if self.step >= LAST_STEP:
            raise ValueError("Обучение завершено")
        return replace(self, step=self.step + 1, **choices)


def demo_actions(state: DemoState) -> list[tuple[str, str]]:
    if state.step == 0:
        return [(f"📦 {label.capitalize()}", state.next(product=code).encode()) for code, label in PRODUCTS.items()]
    if state.step == 1:
        return [(f"⚖️ {weight} кг", state.next(weight=code).encode()) for code, weight in WEIGHTS.items()]
    if state.step == 7:
        return [
            ("🔗 Объединить с ещё одной посылкой", state.next(consolidated="y").encode()),
            ("➡️ Отправить отдельно", state.next(consolidated="n").encode()),
        ]
    if state.step == 11:
        return [(f"📍 {city}", state.next(city=code).encode()) for code, city in CITIES.items()]
    if state.step == LAST_STEP:
        return [("🔁 Пройти ещё раз", DemoState().encode()), ("✅ Перейти в бот", "demo:exit")]
    labels = {
        2: "🛒 Оформить учебный заказ", 3: "🔎 Добавить учебный трек",
        4: "🏭 Посылка поступила на склад", 5: "📷 Посмотреть фото приёмки",
        6: "📦 Что дальше с грузом?", 8: "🚛 Отправить из Китая",
        9: "🛃 Прибытие и таможня", 10: "📍 Выбрать город получения",
        12: "🤝 Получить груз", 13: "💳 Завершить оплату",
    }
    return [(labels[state.step], state.next().encode())]


def demo_card(state: DemoState, rate: Decimal) -> str:
    product = PRODUCTS.get(state.product, "товар")
    weight = WEIGHTS.get(state.weight, Decimal("0"))
    city = CITIES.get(state.city, "город")
    total = estimate_usd(weight, rate) if weight else Decimal("0.00")
    pages = (
        "Выберите учебный товар. Это тренажёр: покупка, посылка и оплата не создаются.",
        f"Вы выбрали {product}. Выберите предполагаемый вес, чтобы увидеть цену доставки.",
        f"Учебный Client ID: <code>DEMO-C000001</code>. На торговой площадке адрес китайского склада указывают целиком, с Client ID в конце.\n\nВес: {weight} кг · ориентир: ${total:.2f} при ${rate:.2f}/кг. Реальный адрес здесь не показываем.",
        f"Учебный заказ: {product}. Вы передали продавцу адрес с Client ID. «Новый запрос» в боте — отдельное обращение к компании, а не покупка на площадке. Здесь условный запрос <code>DEMO-RQ000001</code>.",
        "Продавец дал китайский трек-номер <code>DEMO-LP123456789CN</code>. Клиент передаёт его компании, а администратор привязывает номер к Client ID. После этого номер виден клиенту в «🔎 Мои трек-номера». Статус: «Ожидается на складе».",
        f"Склад сверил Client ID и трек, принял учебную посылку и присвоил <code>DEMO-CG000001</code>. Фактический вес в примере: {weight} кг. В реальности админ добавляет вес, объём, места и 1–10 фотографий.",
        "📷 Учебные фото приёмки: [вид коробки], [этикетка с Client ID], [вес на весах]. Это только описание макета — реальные фотографии здесь не загружаются. В настоящем боте они доступны в «🚚 Мои грузы».",
        "Если у клиента несколько посылок, склад может объединить их в одну упаковку. Выберите, что сделать в учебном примере.",
        ("Две учебные посылки объединены в <code>DEMO-CS000001</code>. Их исходные Cargo остаются в истории." if state.consolidated == "y" else "Учебный груз остаётся отдельным Cargo; консолидация необязательна."),
        "Учебная партия <code>DEMO-SH000001</code> выехала из Китая. Теперь клиент видит отправление и историю статусов в «🚛 Мои отправления».",
        "Путь партии: «Выехал из Китая» → «В пути» → «Прибыл в Таджикистан» → «На таможенном оформлении» → «Таможня пройдена». В реальности каждый статус подтверждает админ после события.",
        "После таможни компания назначает клиенту настоящий пункт выдачи. В этом тренажёре адрес не выдумываем — выберите только город.",
        f"Учебная доставка <code>DEMO-DL000001</code> направлена в {city}, прибыла в пункт выдачи и готова к получению. Реальный адрес клиент увидит после назначения настоящего пункта.",
        "Груз условно выдан клиенту или его представителю. В реальности админ фиксирует имя получателя и факт выдачи; это не происходит автоматически от нажатия клиентом.",
        f"Учебный цикл завершён: условная выдача и оплата отмечены только на экране. Примерная доставка по весу — ${total:.2f}; реальную сумму в TJS компания подтверждает отдельно. Ни платежа, ни заказа, ни записи в БД не создано.",
    )
    return f"🎓 <b>ДЕМО · шаг {state.step + 1}/{LAST_STEP + 1}</b>\n\n{pages[state.step]}\n\n<i>Только обучение. Реальные данные не меняются.</i>"
