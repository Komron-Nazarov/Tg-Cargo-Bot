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
