from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat

from config import Settings
from handlers import admin, cargo, client, consolidation, delivery, shipment, tracking, user, warehouse


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
    dispatcher.include_router(consolidation.router)
    dispatcher.include_router(shipment.router)
    dispatcher.include_router(delivery.router)
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
            BotCommand(command="consolidate", description="Объединить Cargo (админ)"),
            BotCommand(command="consolidations", description="Список консолидаций (админ)"),
            BotCommand(command="consolidation", description="Найти консолидацию (админ)"),
            BotCommand(command="dispatch", description="Оформить выезд из Китая (админ)"),
            BotCommand(command="shipments", description="Последние отправления (админ)"),
            BotCommand(command="shipment", description="Найти отправление (админ)"),
            BotCommand(command="advance", description="Следующий статус Shipment (админ)"),
            BotCommand(command="pickup_add", description="Добавить пункт выдачи (админ)"),
            BotCommand(command="pickups", description="Пункты выдачи (админ)"),
            BotCommand(command="pickup", description="Найти пункт выдачи (админ)"),
            BotCommand(command="assign", description="Назначить доставку клиенту (админ)"),
            BotCommand(command="advance_delivery", description="Следующий статус Delivery (админ)"),
            BotCommand(command="deliveries", description="Последние Delivery (админ)"),
            BotCommand(command="delivery", description="Найти Delivery (админ)"),
        ],
        scope=BotCommandScopeChat(chat_id=admin_id),
    )
