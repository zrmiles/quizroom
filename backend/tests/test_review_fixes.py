"""Регрессии на дефекты B03–B07 из внешнего ревью (2 ноября)."""

import asyncio
from unittest.mock import patch

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.game.engine import Room, manager
from app.game.scoring import is_exact, score
from app.main import app
from app.models import GameSession, Player
from tests.test_audit_fixes import new_quiz
from tests.test_game import join, open_game, recv_until

SINGLE = {
    "id": 1,
    "type": "single",
    "text": "?",
    "time_limit": 1,
    "options": [{"id": 1, "text": "да"}, {"id": 2, "text": "нет"}],
    "correct_option_id": 1,
}


# ---------- B05: точное попадание ----------


def test_exact_requires_being_inside_tolerance():
    assert is_exact(0.15, 0.15, 1)
    assert is_exact(1961, 1961.0, 20)
    assert not is_exact(0.1500000005, 0.15, 1e-12)  # раньше: exact=True при нулевых очках
    assert not is_exact(1e12 + 500, 1e12, 1e9)


def test_narrow_tolerance_gives_consistent_flags_and_points():
    q = {
        "type": "number",
        "time_limit": 20,
        "answer": 0.15,
        "min": 0,
        "max": 1,
        "tolerance": 1e-12,
        "exact_bonus": True,
        "options": [],
    }
    correct, points = score(q, {"number": 0.1500000005}, 0)
    assert (correct, points) == (False, 0)
    assert score(q, {"number": 0.15}, 0) == (True, 2000)


# ---------- B04: время ответа и медленный вход ----------


def test_answer_time_is_taken_when_message_arrives():
    async def scenario():
        room = Room(1, "000001", 1, "Т", [SINGLE])
        p = room.add_player(1, "Аня", {}, "t")
        await room._start_question(0)
        await room.lock.acquire()  # сервер занят дольше, чем длится вопрос
        task = asyncio.create_task(
            room.handle(None, p, {"type": "player:answer", "questionIndex": 0, "value": {"option_id": 1}})
        )
        await asyncio.sleep(1.5)
        room.lock.release()
        await task
        room._cancel_timer()
        return p.answers

    answers = asyncio.run(scenario())
    assert answers[0]["correct"] is True


def test_slow_join_does_not_block_answers(client, host):
    quiz = new_quiz(client, host)
    _, pin = open_game(client, host, quiz)
    first = join(client, pin, "Быстрый")
    room = manager.get(pin)
    right = None

    async def scenario():
        nonlocal right
        await room.handle(None, None, {"type": "host:start"})
        right = room.questions[0]["correct_option_id"]
        entered, release = asyncio.Event(), asyncio.Event()
        original = AsyncSession.commit

        async def slow_commit(db):
            if any(isinstance(row, Player) and row.nickname == "Медленный" for row in db.new):
                entered.set()
                await release.wait()
            return await original(db)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
            with patch.object(AsyncSession, "commit", slow_commit):
                joining = asyncio.create_task(http.post(f"/api/sessions/{pin}/join", json={"nickname": "Медленный"}))
                await asyncio.wait_for(entered.wait(), 2)
                player = room.players[first["player_id"]]
                msg = {"type": "player:answer", "questionIndex": 0, "value": {"option_id": right}}
                await asyncio.wait_for(room.handle(None, player, msg), 1)  # не ждёт запись нового игрока
                assert 0 in player.answers
                release.set()
                assert (await joining).status_code == 201
        room._cancel_timer()

    client.portal.call(scenario)
    assert len(room.players) == 2


# ---------- B03: сбой базы при удалении игрока ----------


def test_kick_keeps_player_when_database_fails(client, host):
    _, pin = open_game(client, host, new_quiz(client, host))
    victim = join(client, pin, "Тролль")
    room = manager.get(pin)

    async def failing_commit(_db):
        raise RuntimeError("база недоступна")

    with client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h:
        recv_until(h, "state:snapshot")
        with patch.object(AsyncSession, "commit", failing_commit):
            h.send_json({"type": "host:kick", "player_id": victim["player_id"]})
            assert "Не удалось удалить" in recv_until(h, "error")["message"]
        assert victim["player_id"] in room.players  # память и база согласованы
        h.send_json({"type": "host:kick", "player_id": victim["player_id"]})  # повтор удаётся
        update = recv_until(h, "lobby:update")
        while update["players"]:
            update = recv_until(h, "lobby:update")
    assert victim["player_id"] not in room.players

    async def rows():
        async with SessionLocal() as db:
            return (await db.scalars(select(Player).where(Player.id == victim["player_id"]))).all()

    assert client.portal.call(rows) == []


# ---------- B07: повтор сохранения итогов ----------


def test_repeated_persist_keeps_original_finish_time(client, host):
    sid, pin = open_game(client, host, new_quiz(client, host))
    join(client, pin, "Игрок")
    room = manager.get(pin)

    async def finished_at():
        async with SessionLocal() as db:
            return (await db.get(GameSession, sid)).finished_at

    async def finish():
        async with room.lock:
            await room._finish()

    client.portal.call(finish)
    first = client.portal.call(finished_at)
    client.portal.call(room._persist)
    assert client.portal.call(finished_at) == first
