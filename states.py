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


class ConsolidationForm(StatesGroup):
    start_confirm = State()
    description = State()
    weight = State()
    volume = State()
    pieces = State()
    photos = State()
    confirm = State()


class ShipmentForm(StatesGroup):
    start_confirm = State()
    transport = State()
    reference = State()
    note = State()
    confirm = State()


class ShipmentAdvanceForm(StatesGroup):
    start_confirm = State()
    note = State()
    confirm = State()


class PickupPointForm(StatesGroup):
    city = State()
    name = State()
    address = State()
    phone = State()
    note = State()
    confirm = State()


class DeliveryAssignForm(StatesGroup):
    confirm = State()


class DeliveryAdvanceForm(StatesGroup):
    start_confirm = State()
    note = State()
    confirm = State()


class HandoverForm(StatesGroup):
    start_confirm = State()
    recipient_type = State()
    recipient_name = State()
    recipient_phone = State()
    note = State()
    confirm = State()


class PaymentForm(StatesGroup):
    amount = State()
    method = State()
    reference = State()
    note = State()
    confirm = State()
