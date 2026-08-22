import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from asyncpg import Pool

from bot_app import create_bot, create_dispatcher, set_commands
from config import Settings
from database import create_pool
from migrations.runner import run_migrations

logger = logging.getLogger(__name__)
BOT_KEY = web.AppKey("bot", Bot)
DISPATCHER_KEY = web.AppKey("dispatcher", Dispatcher)
POOL_KEY = web.AppKey("pool", Pool)


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def create_webhook_app(settings: Settings) -> web.Application:
    bot = create_bot(settings)
    dispatcher = create_dispatcher(settings)
    app = web.Application()
    app[BOT_KEY] = bot
    app[DISPATCHER_KEY] = dispatcher

    async def startup(application: web.Application) -> None:
        pool = None
        try:
            pool = await create_pool(settings)
            await run_migrations(pool)
            application[POOL_KEY] = pool
            dispatcher["pool"] = pool

            await bot.set_webhook(
                url=settings.webhook_url,
                secret_token=settings.webhook_secret,
                drop_pending_updates=False,
            )
            await set_commands(bot, settings.admin_id)
            logger.info("Telegram webhook installed")
            logger.info("Webhook HTTP application initialized")
        except Exception:
            if pool is not None:
                await pool.close()
            await bot.session.close()
            raise

    async def cleanup(application: web.Application) -> None:
        logger.info("Webhook application is stopping")
        pool = application.get(POOL_KEY)
        if pool is not None:
            await pool.close()
        await bot.session.close()

    app.router.add_get("/health", health)
    SimpleRequestHandler(
        dispatcher=dispatcher,
        bot=bot,
        secret_token=settings.webhook_secret,
    ).register(app, path=settings.webhook_path)
    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    setup_application(app, dispatcher, bot=bot)
    return app


def run_webhook(settings: Settings) -> None:
    logger.info("Starting webhook HTTP server on 0.0.0.0:%s", settings.port)
    web.run_app(
        create_webhook_app(settings),
        host="0.0.0.0",
        port=settings.port,
        print=None,
    )
