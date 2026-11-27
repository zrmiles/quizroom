"""Окружение Alembic: и для запуска из приложения, и для ручных команд `alembic ...`."""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app import models  # noqa: F401  — регистрирует таблицы в metadata
from app.db import Base

target_metadata = Base.metadata


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite не умеет большинство ALTER TABLE: Alembic пересоздаёт таблицу целиком.
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_standalone() -> None:
    from app.config import settings

    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
        await connection.commit()
    await engine.dispose()


# Приложение передаёт своё соединение (см. app.db.init_db); ручная команда — создаёт его сама.
connection = context.config.attributes.get("connection")
if connection is not None:
    run_migrations(connection)
else:
    asyncio.run(run_standalone())
