import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat

from config import SETTINGS
from database import create_pool
from handlers import admin, user
from migrations.runner import run_migrations

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
        scope=BotCommandScopeChat(chat_id=SETTINGS.admin_id),
    )


async def main():
    bot = Bot(
        token=SETTINGS.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    pool = await create_pool(SETTINGS)
    await run_migrations(pool)
    dp["pool"] = pool

    dp.include_router(admin.router)
    dp.include_router(user.router)

    await set_commands(bot)

    logging.info("Bot started...")
    try:
        await dp.start_polling(bot)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
