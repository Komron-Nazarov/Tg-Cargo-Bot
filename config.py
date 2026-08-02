# import os
# from dotenv import load_dotenv

# load_dotenv()

# BOT_TOKEN = os.getenv("BOT_TOKEN")
# ADMIN_ID = int(os.getenv("ADMIN_ID"))







import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "cargo_bot")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

# "disable" для локального Postgres, "require" для Supabase (там SSL обязателен)
DB_SSL = os.getenv("DB_SSL", "require")

# DSN для asyncpg
DB_DSN = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в .env")

if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID не найден в .env")