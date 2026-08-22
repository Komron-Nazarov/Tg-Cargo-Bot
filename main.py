import asyncio
import logging

from config import POLLING_MODE, load_settings
from runners.polling import run_polling
from runners.webhook import run_webhook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    settings = load_settings()
    logger.info("Selected deployment mode: %s", settings.deploy_mode)

    if settings.deploy_mode == POLLING_MODE:
        asyncio.run(run_polling(settings))
    else:
        run_webhook(settings)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Application startup failed")
        raise
