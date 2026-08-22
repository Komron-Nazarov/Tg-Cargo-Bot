from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat

from config import Settings
from handlers import admin, cargo, client, tracking, user, warehouse


def create_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher(settings: Settings) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["settings"] = settings
    dispatcher.include_router(admin.router)
    dispatcher.include_router(warehouse.router)
    dispatcher.include_router(client.router)
    dispatcher.include_router(tracking.router)
    dispatcher.include_router(cargo.router)
    dispatcher.include_router(user.router)
    return dispatcher


async def set_commands(bot: Bot, admin_id: int) -> None:
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать"),
        BotCommand(command="cancel", description="Отменить текущее действие"),
    ])
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать"),
            BotCommand(command="cancel", description="Отменить текущее действие"),
            BotCommand(command="orders", description="Список новых заявок (админ)"),
            BotCommand(command="trackings", description="Ожидаемые трек-номера (админ)"),
            BotCommand(command="tracking", description="Поиск трек-номера (админ)"),
            BotCommand(command="receive", description="Принять посылку на склад (админ)"),
            BotCommand(command="cargos", description="Последние Cargo (админ)"),
            BotCommand(command="cargo", description="Найти Cargo ID (админ)"),
        ],
        scope=BotCommandScopeChat(chat_id=admin_id),
    )
