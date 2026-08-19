import os
from dataclasses import dataclass
from typing import Mapping, Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_id: int
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    db_ssl: str


def load_settings(environ: Optional[Mapping[str, str]] = None) -> Settings:
    if environ is None:
        load_dotenv()
        environ = os.environ

    def required(name: str) -> str:
        value = environ.get(name, "").strip()
        if not value:
            raise RuntimeError(f"Обязательная переменная окружения {name} не задана")
        return value

    try:
        admin_id = int(required("ADMIN_ID"))
    except ValueError as exc:
        raise RuntimeError("ADMIN_ID должен быть целым числом") from exc
    if admin_id <= 0:
        raise RuntimeError("ADMIN_ID должен быть положительным числом")

    try:
        db_port = int(environ.get("DB_PORT", "5432"))
    except ValueError as exc:
        raise RuntimeError("DB_PORT должен быть целым числом") from exc
    if not 1 <= db_port <= 65535:
        raise RuntimeError("DB_PORT должен быть в диапазоне 1..65535")

    db_ssl = environ.get("DB_SSL", "require").strip().lower()
    if db_ssl not in {"disable", "require", "verify-ca", "verify-full"}:
        raise RuntimeError("DB_SSL должен быть disable, require, verify-ca или verify-full")

    return Settings(
        bot_token=required("BOT_TOKEN"),
        admin_id=admin_id,
        db_host=required("DB_HOST"),
        db_port=db_port,
        db_name=required("DB_NAME"),
        db_user=required("DB_USER"),
        db_password=required("DB_PASSWORD"),
        db_ssl=db_ssl,
    )


SETTINGS = load_settings()
