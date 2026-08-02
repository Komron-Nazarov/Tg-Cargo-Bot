from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from config import ADMIN_ID


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject) -> bool:
        return event.from_user is not None and event.from_user.id == ADMIN_ID