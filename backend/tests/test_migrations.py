"""Миграции схемы: старая база без Alembic обновляется без потери данных."""

import tempfile

from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import alembic_config, enable_sqlite_foreign_keys, init_db

LEGACY_ROWS = """
INSERT INTO users (id, email, username, password_hash) VALUES (1, 'a@example.com', 'Учитель', 'x');
INSERT INTO quizzes (id, owner_id, title, description, is_public) VALUES (1, 1, 'Викторина', '', 0);
INSERT INTO game_sessions (id, quiz_id, host_id, pin, title, status, snapshot)
    VALUES (1, 1, 1, '123456', 'Игра', 'finished', '[]');
INSERT INTO players (id, session_id, nickname, avatar, token, final_score, reconnects)
    VALUES (1, 1, 'Аня', '{}', 't1', 900, 0);
INSERT INTO player_answers (player_id, question_index, value, is_correct, response_ms, points)
    VALUES (1, 0, '{}', 1, 100, 900);
"""


def _counts(conn):
    tables = ("users", "quizzes", "game_sessions", "players", "player_answers")
    return {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}


def test_legacy_database_is_stamped_and_upgraded_without_losing_rows(client):
    # Клиент нужен ради цикла событий портала: движок базы ниже живёт в нём.
    url = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/legacy.db"

    async def scenario():
        engine = create_async_engine(url)
        # Как в приложении: внешние ключи включены — иначе каскадное удаление при пересоздании таблиц не проявится.
        enable_sqlite_foreign_keys(engine)
        # База «как раньше»: схема начальной ревизии, данные, но без таблицы alembic_version.
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: command.upgrade(alembic_config(c), "0001"))
            await conn.execute(text("DROP TABLE alembic_version"))
            for statement in filter(str.strip, LEGACY_ROWS.split(";")):
                await conn.execute(text(statement))
        async with engine.connect() as conn:
            before = await conn.run_sync(_counts)

        await init_db(engine)
        await init_db(engine)  # повторный запуск ничего не меняет

        async with engine.connect() as conn:
            after = await conn.run_sync(_counts)
            version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            # Удаление викторины больше не стирает её игры.
            await conn.execute(text("DELETE FROM quizzes"))
            kept = (await conn.execute(text("SELECT quiz_id FROM game_sessions"))).all()
            await conn.commit()
        await engine.dispose()
        return before, after, version, kept

    before, after, version, kept = client.portal.call(scenario)
    assert before == after and after["players"] == 1 and after["player_answers"] == 1
    assert version == "0002"
    assert kept == [(None,)]


def test_downgrade_and_upgrade_again(client):
    url = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/roundtrip.db"

    async def scenario():
        engine = create_async_engine(url)
        await init_db(engine)
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: command.downgrade(alembic_config(c), "0001"))
        await init_db(engine)
        async with engine.connect() as conn:
            version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        await engine.dispose()
        return version

    assert client.portal.call(scenario) == "0002"
