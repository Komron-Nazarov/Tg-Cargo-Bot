import os
from dataclasses import dataclass
from typing import Mapping, Optional
from urllib.parse import urlparse

from dotenv import load_dotenv

POLLING_MODE = "polling"
WEBHOOK_MODE = "webhook"


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
    deploy_mode: str
    webhook_base_url: Optional[str]
    webhook_path: str
    webhook_secret: Optional[str]
    port: int
    china_warehouse_address: Optional[str]
    china_warehouse_recipient: Optional[str]
    china_warehouse_phone: Optional[str]

    @property
    def webhook_url(self) -> str:
        if self.webhook_base_url is None:
            raise RuntimeError("WEBHOOK_BASE_URL доступен только в webhook-режиме")
        return f"{self.webhook_base_url}{self.webhook_path}"


def load_settings(environ: Optional[Mapping[str, str]] = None) -> Settings:
    if environ is None:
        load_dotenv()
        environ = os.environ

    def required(name: str) -> str:
        value = environ.get(name, "").strip()
        if not value:
            raise RuntimeError(f"Обязательная переменная окружения {name} не задана")
        return value

    bot_token = required("BOT_TOKEN")

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

    deploy_mode = environ.get("DEPLOY_MODE", POLLING_MODE).strip().lower()
    if deploy_mode not in {POLLING_MODE, WEBHOOK_MODE}:
        raise RuntimeError("DEPLOY_MODE должен быть polling или webhook")

    try:
        port = int(environ.get("PORT", "10000"))
    except ValueError as exc:
        raise RuntimeError("PORT должен быть целым числом") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("PORT должен быть в диапазоне 1..65535")

    webhook_path = environ.get("WEBHOOK_PATH", "/telegram/webhook").strip()
    if not webhook_path.startswith("/"):
        raise RuntimeError("WEBHOOK_PATH должен начинаться с /")
    if webhook_path == "/health":
        raise RuntimeError("WEBHOOK_PATH не должен совпадать с /health")

    webhook_base_url = environ.get("WEBHOOK_BASE_URL", "").strip().rstrip("/") or None
    webhook_secret = environ.get("WEBHOOK_SECRET", "").strip() or None

    if deploy_mode == WEBHOOK_MODE:
        if webhook_base_url is None:
            raise RuntimeError("WEBHOOK_BASE_URL обязателен в webhook-режиме")
        parsed_url = urlparse(webhook_base_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise RuntimeError("WEBHOOK_BASE_URL должен быть корректным HTTPS URL")
        if parsed_url.query or parsed_url.fragment:
            raise RuntimeError("WEBHOOK_BASE_URL не должен содержать query или fragment")
        if webhook_secret is None:
            raise RuntimeError("WEBHOOK_SECRET обязателен в webhook-режиме")
        if webhook_secret == bot_token:
            raise RuntimeError("WEBHOOK_SECRET не должен совпадать с BOT_TOKEN")
        if not 1 <= len(webhook_secret) <= 256 or not all(
            char.isalnum() or char in "_-" for char in webhook_secret
        ):
            raise RuntimeError(
                "WEBHOOK_SECRET должен содержать 1..256 символов A-Z, a-z, 0-9, _ или -"
            )

    return Settings(
        bot_token=bot_token,
        admin_id=admin_id,
        db_host=required("DB_HOST"),
        db_port=db_port,
        db_name=required("DB_NAME"),
        db_user=required("DB_USER"),
        db_password=required("DB_PASSWORD"),
        db_ssl=db_ssl,
        deploy_mode=deploy_mode,
        webhook_base_url=webhook_base_url,
        webhook_path=webhook_path,
        webhook_secret=webhook_secret,
        port=port,
        china_warehouse_address=environ.get("CHINA_WAREHOUSE_ADDRESS", "").strip() or None,
        china_warehouse_recipient=environ.get("CHINA_WAREHOUSE_RECIPIENT", "").strip() or None,
        china_warehouse_phone=environ.get("CHINA_WAREHOUSE_PHONE", "").strip() or None,
    )
