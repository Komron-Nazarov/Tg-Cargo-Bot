from aiogram import Router, F
from aiogram.types import Message
from db import add_order
from config import ADMIN_ID

router = Router()

user_data = {}

@router.message(F.text == "/start")
async def start(message: Message):
    await message.answer("🚚 Привет! Это карго бот.\nОтправь имя груза.")

@router.message()
async def flow(message: Message):
    user_id = message.from_user.id

    if user_id not in user_data:
        user_data[user_id] = {}

    data = user_data[user_id]

    if "name" not in data:
        data["name"] = message.text
        await message.answer("📦 Теперь введи вес (кг):")
        return

    if "weight" not in data:
        try:
            data["weight"] = float(message.text)
        except:
            await message.answer("❌ Введи число (например 2.5)")
            return

        await message.answer("🌍 Введи страну доставки:")
        return

    if "country" not in data:
        data["country"] = message.text

        add_order(
            user_id,
            data["name"],
            data["weight"],
            data["country"]
        )

        await message.answer("✅ Заявка создана!")

        if user_id == ADMIN_ID:
            await message.answer("🧠 Ты админ — заявка добавлена в базу.")

        user_data.pop(user_id)