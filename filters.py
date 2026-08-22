from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from config import Settings


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject, settings: Settings) -> bool:
        return event.from_user is not None and event.from_user.id == settings.admin_id
