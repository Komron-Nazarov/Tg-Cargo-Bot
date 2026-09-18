from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Settings
from services.pricing_service import format_estimate, parse_estimate_weight
from states import PriceCalculatorForm

router = Router()


@router.message(Command("calc"))
async def calculate_command(
    message: Message, command: CommandObject, state: FSMContext, settings: Settings
):
    raw_weight = (command.args or "").strip()
    if raw_weight:
        try:
            weight = parse_estimate_weight(raw_weight)
        except ValueError as exc:
            await message.answer(escape(str(exc)) + "\nПример: /calc 2,5")
            return
        await state.clear()
        await message.answer(format_estimate(weight, settings.price_per_kg_usd))
        return
    await state.clear()
    await state.set_state(PriceCalculatorForm.weight)
    await message.answer("🧮 Введите предполагаемый вес в кг, например 2,5. Отмена: /cancel")


@router.message(F.text == "🧮 Калькулятор доставки")
async def calculate_button(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(PriceCalculatorForm.weight)
    await message.answer("🧮 Введите предполагаемый вес в кг, например 2,5. Отмена: /cancel")


@router.callback_query(F.data == "calc:start")
async def calculate_from_welcome(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(PriceCalculatorForm.weight)
    await callback.message.answer("🧮 Введите предполагаемый вес в кг, например 2,5. Отмена: /cancel")
    await callback.answer()


@router.message(StateFilter(PriceCalculatorForm.weight))
async def calculate_weight(message: Message, state: FSMContext, settings: Settings):
    try:
        weight = parse_estimate_weight(message.text or "")
    except ValueError as exc:
        await message.answer(escape(str(exc)) + "\nВведите вес ещё раз или /cancel.")
        return
    await state.clear()
    await message.answer(format_estimate(weight, settings.price_per_kg_usd))
