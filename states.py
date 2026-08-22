from aiogram.fsm.state import State, StatesGroup


class OrderForm(StatesGroup):
    name = State()
    weight = State()
    country = State()
    confirm = State()


class RegistrationForm(StatesGroup):
    full_name = State()
    phone = State()
    city = State()
    custom_city = State()
    confirm = State()


class TrackingForm(StatesGroup):
    number = State()
    confirm = State()


class WarehouseReceiptForm(StatesGroup):
    start_confirm = State()
    description = State()
    weight = State()
    volume = State()
    pieces = State()
    photos = State()
    confirm = State()
