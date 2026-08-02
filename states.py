from aiogram.fsm.state import State, StatesGroup


class OrderForm(StatesGroup):
    name = State()
    weight = State()
    country = State()
    confirm = State()