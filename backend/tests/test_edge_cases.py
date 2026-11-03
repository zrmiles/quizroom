"""Сценарии, найденные при ручном тестировании: таймер, опоздавшие, ничьи, повтор ошибок."""

import time

from app.game.engine import PlayerState, Room
from tests.test_game import answer, join, open_game, recv_until

QUICK_QUIZ = {
    "title": "Быстрая",
    "questions": [
        {
            "type": "single",
            "text": "Вопрос на 5 секунд",
            "time_limit": 5,
            "options": [{"text": "Да", "is_correct": True}, {"text": "Нет"}],
        },
        {
            "type": "number",
            "text": "Год?",
            "time_limit": 5,
            "number_answer": 1961,
            "number_min": 1900,
            "number_max": 2000,
            "number_tolerance": 20,
        },
    ],
}


def make_quiz(client, host, quiz=QUICK_QUIZ):
    r = client.post("/api/quizzes", json=quiz, headers=host["headers"])
    assert r.status_code == 201, r.text
    return r.json()


def test_timer_closes_question_without_answers(client, host):
    quiz = make_quiz(client, host)
    _, pin = open_game(client, host, quiz)
    silent = join(client, pin, "Молчун")
    with (
        client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h,
        client.websocket_connect(f"/ws/game/{pin}?token={silent['token']}") as p,
    ):
        recv_until(h, "state:snapshot")
        recv_until(p, "state:snapshot")
        h.send_json({"type": "host:start"})
        start = recv_until(p, "question:start")
        assert start["endsAt"] - start["serverNow"] == 5000
        t0 = time.monotonic()
        rev = recv_until(p, "question:reveal")
        assert 4.5 < time.monotonic() - t0 < 7
        assert rev["you"] == {
            "answered": False,
            "correct": False,
            "points": 0,
            "exact": False,
            "value": None,
            "score": 0,
            "rank": 1,
        }


def test_late_joiner_gets_current_question_and_host_sees_them(client, host):
    quiz = make_quiz(client, host)
    _, pin = open_game(client, host, quiz)
    first = join(client, pin, "Первый")
    right = next(o["id"] for o in quiz["questions"][0]["options"] if o["is_correct"])
    with (
        client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h,
        client.websocket_connect(f"/ws/game/{pin}?token={first['token']}") as p1,
    ):
        recv_until(h, "state:snapshot")
        recv_until(p1, "state:snapshot")
        h.send_json({"type": "host:start"})
        recv_until(p1, "question:start")
        late = join(client, pin, "Опоздавший")
        update = recv_until(h, "lobby:update")
        while len(update["players"]) < 2:  # сначала может прийти старое обновление
            update = recv_until(h, "lobby:update")
        assert {p["nickname"] for p in update["players"]} == {"Первый", "Опоздавший"}
        with client.websocket_connect(f"/ws/game/{pin}?token={late['token']}") as p2:
            snap = recv_until(p2, "state:snapshot")
            assert snap["state"] == "question" and snap["youAnswered"] is False
            answer(p2, 0, {"option_id": right})
            recv_until(p2, "answer:ack")
            answer(p1, 0, {"option_id": right})
            rev = recv_until(p2, "question:reveal")
            assert rev["you"]["correct"] and rev["you"]["value"] == {"option_id": right}


def test_equal_scores_share_rank():
    room = Room(1, "000000", 1, "Т", [])
    for i, (nick, score) in enumerate([("Аня", 500), ("Борис", 300), ("Вика", 300), ("Гоша", 100)]):
        room.players[i] = PlayerState(id=i, nickname=nick, avatar={}, token=str(i), score=score)
    assert [r["rank"] for r in room.leaderboard()] == [1, 2, 2, 4]


def test_close_number_answer_is_not_exact(client, host):
    quiz = make_quiz(client, host)
    _, pin = open_game(client, host, quiz)
    me = join(client, pin, "Угадайка")
    with (
        client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h,
        client.websocket_connect(f"/ws/game/{pin}?token={me['token']}") as p,
    ):
        recv_until(h, "state:snapshot")
        recv_until(p, "state:snapshot")
        h.send_json({"type": "host:start"})
        recv_until(p, "question:start")
        h.send_json({"type": "host:skip"})
        recv_until(h, "question:reveal")
        h.send_json({"type": "host:next"})
        recv_until(p, "question:start")
        answer(p, 1, {"number": 1950})
        you = recv_until(p, "question:reveal")["you"]
        assert you["exact"] is False and you["points"] > 0 and you["value"] == {"number": 1950}


def test_retry_title_does_not_stack(client, host):
    quiz = make_quiz(client, host)
    sid, pin = open_game(client, host, quiz)
    for _ in range(2):
        p = join(client, pin, "Ошибающийся")
        wrong = next(o["id"] for o in quiz["questions"][0]["options"] if not o["is_correct"])
        with (
            client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h,
            client.websocket_connect(f"/ws/game/{pin}?token={p['token']}") as ws,
        ):
            recv_until(h, "state:snapshot")
            recv_until(ws, "state:snapshot")
            h.send_json({"type": "host:start"})
            recv_until(ws, "question:start")
            answer(ws, 0, {"option_id": wrong})
            recv_until(h, "question:reveal")
            h.send_json({"type": "host:end"})
            recv_until(h, "game:finished")
        r = client.post(f"/api/sessions/{sid}/retry", headers=host["headers"])
        assert r.status_code == 201, r.text
        sid, pin = r.json()["id"], r.json()["pin"]
    title = client.get(f"/api/sessions/{pin}").json()["title"]
    assert title == "Быстрая · работа над ошибками"
