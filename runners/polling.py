import logging

from bot_app import create_bot, create_dispatcher, set_commands
from config import Settings
from database import create_pool
from migrations.runner import run_migrations

logger = logging.getLogger(__name__)


async def run_polling(settings: Settings) -> None:
    bot = create_bot(settings)
    dispatcher = create_dispatcher(settings)
    pool = None

    try:
        pool = await create_pool(settings)
        await run_migrations(pool)
        dispatcher["pool"] = pool

        await bot.delete_webhook(drop_pending_updates=False)
        await set_commands(bot, settings.admin_id)
        logger.info("Telegram polling started")
        await dispatcher.start_polling(bot)
    finally:
        logger.info("Polling application is stopping")
        if pool is not None:
            await pool.close()
        await bot.session.close()
