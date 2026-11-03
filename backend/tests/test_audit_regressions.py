"""Регрессии полного аудита: сбои БД, строгий WS, гонки и медленные клиенты.

Те же тесты запускаются в CI на SQLite и PostgreSQL.
"""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.game.engine as game
from app.config import Settings
from app.db import SessionLocal
from app.main import app
from app.models import GameSession, Player, PlayerAnswer, User
from app.routers.sessions import _session_snapshot, build_snapshot
from app.security import hash_password, verify_password
from tests.test_audit_fixes import new_quiz
from tests.test_game import answer, join, open_game, recv_until


def test_ws_rejects_nonfinite_and_extra_answer_fields(client, host):
    quiz = new_quiz(client, host)
    sid, pin = open_game(client, host, quiz)
    ticket = join(client, pin, "Проверка")
    right = next(o["id"] for o in quiz["questions"][0]["options"] if o["is_correct"])
    with (
        client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h,
        client.websocket_connect(f"/ws/game/{pin}?token={ticket['token']}") as p,
    ):
        recv_until(h, "state:snapshot")
        recv_until(p, "state:snapshot")
        h.send_json({"type": "host:start"})
        recv_until(p, "question:start")
        for extra in ["NaN", "Infinity", "1e309"]:
            p.send_text(
                '{"type":"player:answer","questionIndex":0,"value":{"option_id":'
                + str(right)
                + ',"unused":'
                + extra
                + "}}"
            )
            recv_until(p, "error")
        for value in [{"option_id": right, "unused": 1}, {"option_id": True}, {"option_id": [right]}]:
            answer(p, 0, value)
            recv_until(p, "error")
        assert not game.manager.get(pin).players[ticket["player_id"]].answers
        answer(p, 0, {"option_id": right})
        recv_until(p, "question:reveal")
        h.send_json({"type": "host:next"})
        recv_until(h, "game:finished")
    report = client.get(f"/api/sessions/{sid}/report", headers=host["headers"])
    assert report.status_code == 200
    assert report.json()["players"][0]["correct"] == 1


def test_failed_finish_can_be_retried_without_duplicate_answers(client, host):
    quiz = new_quiz(client, host)
    sid, pin = open_game(client, host, quiz)
    ticket = join(client, pin, "Игрок")
    right = quiz["questions"][0]["options"][0]["id"]
    with (
        client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h,
        client.websocket_connect(f"/ws/game/{pin}?token={ticket['token']}") as p,
    ):
        recv_until(h, "state:snapshot")
        recv_until(p, "state:snapshot")
        h.send_json({"type": "host:start"})
        recv_until(p, "question:start")
        answer(p, 0, {"option_id": right})
        recv_until(h, "question:reveal")
        with patch.object(game, "SessionLocal", side_effect=OSError("temporary outage")):
            h.send_json({"type": "host:next"})
            assert "сохранить" in recv_until(h, "error")["message"]
        assert game.manager.get(pin).state == game.REVEAL
        assert client.get(f"/api/sessions/{sid}/report", headers=host["headers"]).status_code == 409
        h.send_json({"type": "host:next"})
        recv_until(h, "game:finished")
        client.portal.call(game.manager.get(pin)._persist)
    assert client.get(f"/api/sessions/{sid}/report", headers=host["headers"]).json()["players"][0]["correct"] == 1

    async def count_answers():
        async with SessionLocal() as db:
            return await db.scalar(
                select(func.count()).select_from(PlayerAnswer).where(PlayerAnswer.player_id == ticket["player_id"])
            )

    assert client.portal.call(count_answers) == 1


def test_order_ids_are_random_session_ids():
    options = [SimpleNamespace(id=i, text=str(i)) for i in range(1, 5)]
    question = SimpleNamespace(id=1, type="order", options=options, text="Order", time_limit=20)
    with patch("app.routers.sessions.secrets.randbelow", side_effect=[40, 5, 90, 12]):
        snapshot = _session_snapshot(build_snapshot([question]))[0]
    assert snapshot["correct_order"] == [41, 6, 91, 13]
    assert snapshot["correct_order"] != sorted(snapshot["correct_order"])
    assert {o["id"] for o in snapshot["options"]}.isdisjoint({o.id for o in options})


def test_retry_of_legacy_snapshot_remaps_ids_without_modifying_parent():
    original = [
        {"type": "order", "options": [{"id": i, "text": str(i)} for i in [10, 11, 12]], "correct_order": [12, 10, 11]}
    ]
    with patch("app.routers.sessions.secrets.randbelow", side_effect=[40, 5, 90]):
        remapped = _session_snapshot(original)[0]
    assert remapped["correct_order"] == [91, 41, 6]
    assert original[0]["correct_order"] == [12, 10, 11]
    assert [o["id"] for o in original[0]["options"]] == [10, 11, 12]


class Socket:
    def __init__(self, slow=False):
        self.slow = slow
        self.frames = []
        self.received = asyncio.Event()
        self.closed = False

    async def send_json(self, message):
        if self.slow:
            await asyncio.Event().wait()
        self.frames.append(message)
        self.received.set()

    async def close(self, code=1000):
        self.closed = True


def test_slow_sockets_do_not_consume_other_players_time(client, monkeypatch):
    monkeypatch.setattr(game, "SEND_TIMEOUT_S", 0.05)

    async def scenario():
        room = game.Room(
            0,
            "slow",
            0,
            "Slow",
            [
                {
                    "type": "single",
                    "text": "?",
                    "time_limit": 5,
                    "options": [{"id": 1, "text": "yes"}, {"id": 2, "text": "no"}],
                    "correct_option_id": 1,
                }
            ],
        )
        for _ in range(3):
            room.attach(Socket(slow=True), None)
        fast = Socket()
        player = room.add_player(1, "Fast", {}, "token")
        room.attach(fast, player)
        async with room.lock:
            await room._start_question(0)
        await asyncio.wait_for(fast.received.wait(), 0.2)
        assert fast.frames[0]["type"] == "question:start"
        assert room.ends_at_ms - game.now_ms() > 4500
        await room.shutdown("test ended")
        assert fast.closed
        assert not room.outboxes and not room.senders

    client.portal.call(scenario)


def test_outbox_overflow_disconnects_even_before_sender_starts(client):
    async def scenario():
        room = game.Room(0, "overflow", 0, "Overflow", [])
        ws = Socket(slow=True)
        room.attach(ws, None)
        for _ in range(game.OUTBOX_LIMIT + 1):
            await room._send(ws, {"type": "test"})
        assert ws not in room.outboxes and ws not in room.host_sockets
        await room.shutdown("test ended")
        assert ws.closed

    client.portal.call(scenario)


def test_finished_room_sweep_closes_connections(client):
    async def scenario():
        gm = game.GameManager()
        room = gm.create(0, "expiry", 0, "Expired", [])
        ws = Socket()
        room.attach(ws, None)
        room.state = game.FINISHED
        room.last_activity -= game.FINISHED_ROOM_TTL_S + 1
        await gm.sweep()
        assert gm.get("expiry") is None
        assert ws.closed and not room.host_sockets and not room.senders

    client.portal.call(scenario)


def test_concurrent_sessions_reserve_pin_before_commit(client, host, monkeypatch):
    quiz = new_quiz(client, host)
    values = iter([123456, 123456, 654321])
    monkeypatch.setattr(game.secrets, "randbelow", lambda _: next(values))

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        original = AsyncSession.commit

        async def commit(db):
            if any(isinstance(row, GameSession) and row.pin == "123456" for row in db.new):
                entered.set()
                await release.wait()
            return await original(db)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
            with patch.object(AsyncSession, "commit", commit):
                first = asyncio.create_task(
                    http.post("/api/sessions", headers=host["headers"], json={"quiz_id": quiz["id"]})
                )
                await asyncio.wait_for(entered.wait(), 2)
                second = await http.post("/api/sessions", headers=host["headers"], json={"quiz_id": quiz["id"]})
                release.set()
                first_response = await first
            assert first_response.status_code == second.status_code == 201
            assert {first_response.json()["pin"], second.json()["pin"]} == {"123456", "654321"}

    client.portal.call(scenario)


def test_join_racing_finish_leaves_no_ghost_players(client, host):
    sid, pin = open_game(client, host, new_quiz(client, host))
    join(client, pin, "Existing")

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        original = AsyncSession.commit
        room = game.manager.get(pin)

        async def commit(db):
            if any(isinstance(row, Player) and row.nickname == "Delayed" for row in db.new):
                entered.set()
                await release.wait()
            return await original(db)

        async def finish():
            async with room.lock:
                await room._finish()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
            with patch.object(AsyncSession, "commit", commit):
                joining = asyncio.create_task(http.post(f"/api/sessions/{pin}/join", json={"nickname": "Delayed"}))
                await asyncio.wait_for(entered.wait(), 2)
                finishing = asyncio.create_task(finish())
                await asyncio.sleep(0)
                assert not finishing.done()
                release.set()
                # Вход идёт в две фазы: игра успела закончиться, поэтому опоздавший не принят
                # и его строка удалена — в отчёте нет «призрачного» участника без места.
                assert (await joining).status_code == 404
                await finishing
            report = (await http.get(f"/api/sessions/{sid}/report", headers=host["headers"])).json()
            assert [p["nickname"] for p in report["players"]] == ["Existing"]
            assert all(player["rank"] is not None for player in report["players"])

    client.portal.call(scenario)


def test_concurrent_registration_returns_conflict(client):
    email = f"concurrent-{uuid4().hex}@example.com"

    async def scenario():
        count = 0
        ready = asyncio.Event()
        original = AsyncSession.commit

        async def commit(db):
            nonlocal count
            if any(isinstance(row, User) and row.email == email for row in db.new):
                count += 1
                if count == 2:
                    ready.set()
                await asyncio.wait_for(ready.wait(), 3)
            return await original(db)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
            with patch.object(AsyncSession, "commit", commit):
                responses = await asyncio.gather(
                    *[
                        http.post(
                            "/api/auth/register",
                            json={
                                "email": email,
                                "username": "Audit",
                                "password": "password123",
                            },
                        )
                        for _ in range(2)
                    ]
                )
            assert sorted(r.status_code for r in responses) == [201, 409]

    client.portal.call(scenario)


def test_password_work_does_not_block_health(client, host):
    entered, release = threading.Event(), threading.Event()

    def slow_check(*_):
        entered.set()
        release.wait(3)
        return True

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
            with patch("app.routers.auth.verify_password", slow_check):
                login = asyncio.create_task(
                    http.post(
                        "/api/auth/login",
                        json={
                            "email": host["email"],
                            "password": "password123",
                        },
                    )
                )
                try:
                    assert await asyncio.to_thread(entered.wait, 2)
                    assert not login.done()
                    assert (await asyncio.wait_for(http.get("/api/health"), 0.5)).status_code == 200
                finally:
                    release.set()
                assert (await login).status_code == 200

    client.portal.call(scenario)


def test_login_attempts_are_limited(client):
    payload = {"email": "unknown@example.com", "password": "password123"}
    for _ in range(20):
        assert client.post("/api/auth/login", json=payload).status_code == 401
    response = client.post("/api/auth/login", json=payload)
    assert response.status_code == 429 and response.headers["retry-after"] == "60"


def test_secret_must_be_configured_and_not_short(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret="dev-secret-change-me")


def test_login_does_not_truncate_password_bytes(client):
    password = "я" * 35 + "ab"
    assert not verify_password(password + "different", hash_password(password))
    assert (
        client.post(
            "/api/auth/login",
            json={
                "email": "long@example.com",
                "password": password + "different",
            },
        ).status_code
        == 422
    )
