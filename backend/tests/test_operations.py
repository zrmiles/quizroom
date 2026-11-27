"""Эксплуатация: проверка здоровья, постраничная история, логи, время ответов в отчёте."""

import json
import logging
from unittest.mock import patch

from sqlalchemy import select

from app.db import SessionLocal
from app.logging_setup import JsonFormatter
from app.models import PlayerAnswer
from tests.conftest import game_ws
from tests.test_game import answer, join, open_game, recv_until


def test_health_checks_database(client):
    ok = client.get("/api/health")
    assert ok.status_code == 200 and ok.headers["x-content-type-options"] == "nosniff"
    with patch("app.main.SessionLocal", side_effect=OSError("db down")):
        assert client.get("/api/health").status_code == 503


def test_history_is_paginated(client, host, quiz):
    created = [open_game(client, host, quiz)[0] for _ in range(3)]
    first = client.get("/api/sessions/history?limit=2", headers=host["headers"]).json()
    assert [h["id"] for h in first] == created[::-1][:2]
    rest = client.get(f"/api/sessions/history?limit=2&before={first[-1]['id']}", headers=host["headers"]).json()
    assert [h["id"] for h in rest] == [created[0]]


def test_answer_time_is_when_player_answered(client, host, quiz):
    sid, pin = open_game(client, host, quiz)
    me = join(client, pin, "Аня")
    right = next(o["id"] for o in quiz["questions"][0]["options"] if o["is_correct"])
    with game_ws(client, pin, host["token"], "host") as h, game_ws(client, pin, me["token"]) as p:
        recv_until(h, "state:snapshot")
        recv_until(p, "state:snapshot")
        h.send_json({"type": "host:start"})
        recv_until(p, "question:start")
        answer(p, 0, {"option_id": right})
        recv_until(h, "question:reveal")
        at_memory = client.portal.call(lambda: _memory_time(pin, me["player_id"]))
        h.send_json({"type": "host:end"})
        recv_until(h, "game:finished")

    async def stored():
        async with SessionLocal() as db:
            return await db.scalar(select(PlayerAnswer.answered_at).where(PlayerAnswer.player_id == me["player_id"]))

    saved = client.portal.call(stored)
    assert abs(saved.replace(tzinfo=None) - at_memory.replace(tzinfo=None)).total_seconds() < 1


async def _memory_time(pin, player_id):
    from app.game.engine import manager

    return manager.get(pin).players[player_id].answers[0]["at"]


def test_json_log_line():
    record = logging.LogRecord("quizroom", logging.ERROR, __file__, 1, "Комната %s", ("123456",), None)
    line = json.loads(JsonFormatter().format(record))
    assert line["level"] == "ERROR" and line["message"] == "Комната 123456" and line["logger"] == "quizroom"
