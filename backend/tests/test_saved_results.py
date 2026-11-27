"""Итоги игры записываются после каждого вопроса и не теряются, если игру не завершили (B01)."""

import asyncio
from unittest.mock import patch

from sqlalchemy import select

from app.db import SessionLocal
from app.game import engine as game
from app.models import GameSession, Player, PlayerAnswer
from tests.conftest import game_ws
from tests.test_audit_fixes import new_quiz
from tests.test_game import answer, join, open_game, recv_until

TWO = {
    "title": "Два вопроса",
    "questions": [
        {
            "type": "single",
            "text": f"Вопрос {n}",
            "time_limit": 20,
            "options": [{"text": "да", "is_correct": True}, {"text": "нет"}],
        }
        for n in (1, 2)
    ],
}


def options(quiz, i):
    opts = quiz["questions"][i]["options"]
    return next(o["id"] for o in opts if o["is_correct"]), next(o["id"] for o in opts if not o["is_correct"])


def play_first_question(client, host, quiz, pin, ticket, correct=True):
    """Ведущий запускает игру, игрок отвечает на первый вопрос; комната остаётся на разборе."""
    right, wrong = options(quiz, 0)
    with (
        game_ws(client, pin, host["token"], "host") as h,
        game_ws(client, pin, ticket["token"]) as p,
    ):
        recv_until(h, "state:snapshot")
        recv_until(p, "state:snapshot")
        h.send_json({"type": "host:start"})
        recv_until(p, "question:start")
        answer(p, 0, {"option_id": right if correct else wrong})
        recv_until(h, "question:reveal")
        recv_until(p, "question:reveal")
    wait_saved(client, pin)


def wait_saved(client, pin):
    """Промежуточная запись идёт отдельной задачей — дожидаемся её."""

    async def wait():
        room = game.manager.get(pin)
        if room is not None:
            await asyncio.gather(*list(room.savers))

    client.portal.call(wait)


def stored(client, sid):
    async def read():
        async with SessionLocal() as db:
            gs = await db.get(GameSession, sid)
            players = (await db.scalars(select(Player).where(Player.session_id == sid))).all()
            answers = (
                await db.scalars(select(PlayerAnswer).where(PlayerAnswer.player_id.in_([p.id for p in players])))
            ).all()
            return gs.status, [(p.nickname, p.final_score, p.final_rank) for p in players], len(answers)

    return client.portal.call(read)


def make_idle(pin, seconds):
    game.manager.get(pin).last_activity -= seconds + 1


def test_answers_are_saved_when_each_question_closes(client, host):
    quiz = new_quiz(client, host, TWO)
    sid, pin = open_game(client, host, quiz)
    ticket = join(client, pin, "Аня")
    play_first_question(client, host, quiz, pin, ticket)

    status, players, answers = stored(client, sid)
    assert status == "running"
    assert answers == 1
    assert players[0][0] == "Аня" and players[0][1] > 0 and players[0][2] == 1
    # Игра ещё идёт: отчёта пока нет.
    assert client.get(f"/api/sessions/{sid}/report", headers=host["headers"]).status_code == 409


def test_abandoned_game_keeps_report_of_played_questions(client, host):
    quiz = new_quiz(client, host, TWO)
    sid, pin = open_game(client, host, quiz)
    ticket = join(client, pin, "Аня")
    play_first_question(client, host, quiz, pin, ticket, correct=False)

    make_idle(pin, game.IDLE_ROOM_TTL_S)
    client.portal.call(game.manager.sweep)
    assert game.manager.get(pin) is None

    r = client.get(f"/api/sessions/{sid}/report", headers=host["headers"])
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["session"]["status"] == "aborted"
    assert rep["summary"]["interrupted"] is True
    assert rep["summary"]["shown_count"] == 1
    assert [q["shown"] for q in rep["questions"]] == [True, False]
    assert rep["players"][0]["cells"][0]["state"] == "wrong"

    item = next(h for h in client.get("/api/sessions/history", headers=host["headers"]).json() if h["id"] == sid)
    assert item["status"] == "aborted" and item["has_report"] is True
    # Ошибку из прерванной игры можно разобрать повтором.
    assert client.post(f"/api/sessions/{sid}/retry", headers=host["headers"]).status_code == 201


def test_unattended_last_reveal_is_finished_automatically(client, host):
    quiz = new_quiz(client, host)  # один вопрос: его разбор — последний
    sid, pin = open_game(client, host, quiz)
    ticket = join(client, pin, "Аня")
    play_first_question(client, host, quiz, pin, ticket)

    # Раньше срока ничего не происходит: ведущий может ещё обсуждать ответ.
    make_idle(pin, game.LAST_REVEAL_IDLE_S - 60)
    client.portal.call(game.manager.sweep)
    assert game.manager.get(pin).state == game.REVEAL

    make_idle(pin, 60)
    client.portal.call(game.manager.sweep)
    room = game.manager.get(pin)
    assert room is not None and room.state == game.FINISHED  # итоги ещё доступны для переподключения
    rep = client.get(f"/api/sessions/{sid}/report", headers=host["headers"]).json()
    assert rep["session"]["status"] == "finished" and rep["summary"]["interrupted"] is False
    assert rep["players"][0]["correct"] == 1


def test_server_shutdown_saves_closed_questions_but_not_the_open_one(client, host):
    quiz = new_quiz(client, host, TWO)
    sid, pin = open_game(client, host, quiz)
    ticket = join(client, pin, "Аня")
    right0, _ = options(quiz, 0)
    right1, _ = options(quiz, 1)
    with (
        game_ws(client, pin, host["token"], "host") as h,
        game_ws(client, pin, ticket["token"]) as p,
    ):
        recv_until(h, "state:snapshot")
        recv_until(p, "state:snapshot")
        h.send_json({"type": "host:start"})
        recv_until(p, "question:start")
        answer(p, 0, {"option_id": right0})
        first = recv_until(p, "question:reveal")["you"]["points"]
        h.send_json({"type": "host:next", "questionIndex": 0})
        recv_until(p, "question:start")
        # Второй вопрос ещё идёт; ответ дан, но разбора не было.
        game.manager.get(pin).players[ticket["player_id"]].answers[1] = {
            "value": {"option_id": right1},
            "correct": True,
            "points": 900,
            "ms": 100,
            "exact": False,
        }
        game.manager.get(pin).players[ticket["player_id"]].score += 900
    wait_saved(client, pin)

    client.portal.call(game.manager.close_all, "Сервер перезапускается")
    rep = client.get(f"/api/sessions/{sid}/report", headers=host["headers"]).json()
    assert rep["summary"]["interrupted"] is True
    assert [q["shown"] for q in rep["questions"]] == [True, False]
    assert rep["players"][0]["score"] == first
    assert rep["players"][0]["cells"][1]["state"] == "unshown"


def test_game_aborted_before_first_reveal_has_no_report(client, host):
    quiz = new_quiz(client, host, TWO)
    sid, pin = open_game(client, host, quiz)
    ticket = join(client, pin, "Аня")
    with (
        game_ws(client, pin, host["token"], "host") as h,
        game_ws(client, pin, ticket["token"]) as p,
    ):
        recv_until(h, "state:snapshot")
        recv_until(p, "state:snapshot")
        h.send_json({"type": "host:start"})
        recv_until(p, "question:start")
    client.portal.call(game.manager.close_all, "Сервер перезапускается")

    r = client.get(f"/api/sessions/{sid}/report", headers=host["headers"])
    assert r.status_code == 409 and "прервана" in r.json()["detail"]
    item = next(h for h in client.get("/api/sessions/history", headers=host["headers"]).json() if h["id"] == sid)
    assert item["has_report"] is False


def test_failed_checkpoint_does_not_break_the_game(client, host):
    quiz = new_quiz(client, host)
    sid, pin = open_game(client, host, quiz)
    ticket = join(client, pin, "Аня")
    play_first_question(client, host, quiz, pin, ticket)
    room = game.manager.get(pin)

    with patch.object(game, "SessionLocal", side_effect=OSError("temporary outage")):
        client.portal.call(room._checkpoint)  # ошибка записывается в лог, а не прерывает игру
    assert room.state == game.REVEAL

    async def finish():
        async with room.lock:
            await room._finish()

    client.portal.call(finish)
    assert client.get(f"/api/sessions/{sid}/report", headers=host["headers"]).json()["players"][0]["correct"] == 1


def test_checkpoint_keeps_player_whose_join_is_still_in_progress(client, host):
    """Вход идёт в две фазы: строка игрока уже в базе, а в комнате его ещё нет."""
    quiz = new_quiz(client, host, TWO)
    sid, pin = open_game(client, host, quiz)
    ticket = join(client, pin, "Аня")
    play_first_question(client, host, quiz, pin, ticket)
    room = game.manager.get(pin)

    async def add_pending_row():
        async with SessionLocal() as db:
            db.add(Player(session_id=sid, nickname="Входит", avatar={}, token="pending-join-token"))
            await db.commit()

    client.portal.call(add_pending_row)
    client.portal.call(room._checkpoint)
    assert "Входит" in [name for name, _, _ in stored(client, sid)[1]]

    async def finish():
        async with room.lock:
            await room._finish()

    # Окончательная запись убирает строки, которые так и не стали игроками комнаты.
    client.portal.call(finish)
    assert [name for name, _, _ in stored(client, sid)[1]] == ["Аня"]
