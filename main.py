# import asyncio
# from aiogram import Bot, Dispatcher
# from config import BOT_TOKEN
# from handlers import router

# bot = Bot(token=BOT_TOKEN)
# dp = Dispatcher()

# dp.include_router(router)

# async def main():
#     print("Bot started...")
#     await dp.start_polling(bot)

# if __name__ == "__main__":
#     asyncio.run(main())
# else:
#     print("Bot stopped.")











import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat

import db
from config import ADMIN_ID, BOT_TOKEN, DB_DSN, DB_SSL
from handlers import admin, user

logging.basicConfig(level=logging.INFO)


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать"),
        BotCommand(command="cancel", description="Отменить текущую заявку"),
    ])
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать"),
            BotCommand(command="cancel", description="Отменить текущую заявку"),
            BotCommand(command="orders", description="Список новых заявок (админ)"),
        ],
        scope=BotCommandScopeChat(chat_id=ADMIN_ID),
    )


async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # Пул соединений создаётся один раз при старте, а не блокирующим вызовом
    # на уровне модуля, как было в первой версии db.py
    pool = await db.create_pool(DB_DSN, ssl_mode=DB_SSL)
    dp["pool"] = pool  # прокидывается во все хендлеры как именованный параметр

    dp.include_router(admin.router)  # раньше user.router, чтобы /orders не перехватывался
    dp.include_router(user.router)

    await set_commands(bot)

    logging.info("Bot started...")
    try:
        await dp.start_polling(bot)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())