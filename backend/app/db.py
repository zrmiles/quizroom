from collections.abc import AsyncIterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, event, inspect
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# pool_pre_ping: после перезапуска PostgreSQL мёртвые соединения из пула не превращаются в ошибки 500.
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


def enable_sqlite_foreign_keys(target: AsyncEngine) -> None:
    """В SQLite внешние ключи (и ON DELETE CASCADE) выключены по умолчанию — включаем на каждом соединении."""
    if target.dialect.name != "sqlite":
        return

    def on_connect(dbapi_conn, _record) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(target.sync_engine, "connect", on_connect)


enable_sqlite_foreign_keys(engine)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


# Ревизия, которой соответствует схема, создававшаяся раньше через create_all.
BASE_REVISION = "0001"
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(connection: Connection | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def _upgrade(connection: Connection) -> None:
    config = alembic_config(connection)
    tables = set(inspect(connection).get_table_names())
    if "users" in tables and "alembic_version" not in tables:
        # База создана до появления миграций: её схема совпадает с начальной ревизией.
        command.stamp(config, BASE_REVISION)
    command.upgrade(config, "head")


async def init_db(target: AsyncEngine | None = None) -> None:
    """Приводит схему базы к последней миграции. Вызывается при каждом запуске приложения."""
    async with (target or engine).connect() as conn:
        sqlite = conn.dialect.name == "sqlite"
        if sqlite:
            # SQLite меняет таблицу через пересоздание (DROP TABLE + копия). С включёнными внешними ключами
            # DROP каскадом удалил бы всех игроков и ответы. Прагма действует только вне транзакции,
            # поэтому выполняется первой.
            await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            await conn.run_sync(_upgrade)
            if sqlite:
                broken = (await conn.exec_driver_sql("PRAGMA foreign_key_check")).fetchall()
                if broken:
                    await conn.rollback()
                    raise RuntimeError(f"Миграция нарушила внешние ключи: {broken[:5]}")
            await conn.commit()
        finally:
            if sqlite:
                await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
