import hashlib
import logging
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).parent / "sql"

CREATE_MIGRATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


async def run_migrations(pool: asyncpg.Pool) -> None:
    """Apply pending SQL files once and reject modified applied migrations."""
    async with pool.acquire() as conn:
        await conn.execute(CREATE_MIGRATIONS_TABLE_SQL)
        applied = {
            row["version"]: row["checksum"]
            for row in await conn.fetch("SELECT version, checksum FROM schema_migrations")
        }

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = path.stem
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()

            if version in applied:
                if applied[version] != checksum:
                    raise RuntimeError(f"Применённая миграция {path.name} была изменена")
                continue

            logger.info("Applying database migration %s", path.name)
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version, checksum) VALUES ($1, $2)",
                    version,
                    checksum,
                )
