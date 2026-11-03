"""Регрессионные тесты на баги, найденные при аудите кода."""

import time

import pytest
from starlette.websockets import WebSocketDisconnect

from app.game.engine import IDLE_ROOM_TTL_S, manager
from tests.conftest import register
from tests.test_game import AVATAR, join, open_game, recv_until

ONE = {
    "title": "Аудит",
    "questions": [
        {
            "type": "single",
            "text": "?",
            "time_limit": 20,
            "options": [{"text": "да", "is_correct": True}, {"text": "нет"}],
        }
    ],
}


def new_quiz(client, host, quiz=ONE):
    r = client.post("/api/quizzes", json=quiz, headers=host["headers"])
    assert r.status_code == 201, r.text
    return r.json()


# ---------- проверка входных данных ----------


def test_infinity_in_number_question_is_rejected_and_not_saved(client, host):
    raw = (
        '{"title":"Inf","questions":[{"type":"number","text":"?","number_answer":5,'
        '"number_min":0,"number_max":Infinity,"number_tolerance":1}]}'
    )
    r = client.post("/api/quizzes", content=raw, headers={**host["headers"], "Content-Type": "application/json"})
    assert r.status_code == 422
    assert client.get("/api/quizzes", headers=host["headers"]).json() == []


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"username": "  a  ", "password": "password123"}, "username"),
        ({"username": "Аня", "password": "я" * 40}, "password"),
    ],
)
def test_register_rejects_bad_names_and_long_cyrillic_passwords(client, payload, field):
    r = client.post("/api/auth/register", json={"email": "x@example.com", **payload})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"][-1] == field


def test_blank_title_is_rejected(client, host):
    assert client.post("/api/quizzes", json={**ONE, "title": "    "}, headers=host["headers"]).status_code == 422


def test_updated_at_changes_when_only_questions_change(client, host):
    quiz = new_quiz(client, host)
    time.sleep(1.1)  # у SQLite точность now() — секунда
    edited = {**ONE, "questions": [{**ONE["questions"][0], "text": "Новый текст"}]}
    after = client.put(f"/api/quizzes/{quiz['id']}", json=edited, headers=host["headers"]).json()
    assert after["updated_at"] != quiz["updated_at"]


# ---------- комнаты ----------


def test_reserved_nickname_counts_as_taken(client, host):
    _, pin = open_game(client, host, new_quiz(client, host))
    manager.get(pin).reserved_nicks.add("двойник")
    r = client.post(f"/api/sessions/{pin}/join", json={"nickname": "Двойник"})
    assert r.status_code == 409


def test_deleting_quiz_closes_its_live_room(client, host):
    quiz = new_quiz(client, host)
    _, pin = open_game(client, host, quiz)
    p = join(client, pin, "Игрок")
    with client.websocket_connect(f"/ws/game/{pin}?token={p['token']}") as ws:
        recv_until(ws, "state:snapshot")
        assert client.delete(f"/api/quizzes/{quiz['id']}", headers=host["headers"]).status_code == 204
        assert "удалил" in recv_until(ws, "error")["message"]
    r = client.post(f"/api/sessions/{pin}/join", json={"nickname": "Новый", "avatar": AVATAR})
    assert r.status_code == 404


def test_abandoned_room_is_swept_and_marked_aborted(client, host):
    sid, pin = open_game(client, host, new_quiz(client, host))
    manager.get(pin).last_activity -= IDLE_ROOM_TTL_S + 1
    client.portal.call(manager.sweep)
    assert manager.get(pin) is None
    r = client.get(f"/api/sessions/{sid}/report", headers=host["headers"])
    assert r.status_code == 409 and "прервана" in r.json()["detail"]


# ---------- WebSocket ----------


def test_token_can_be_sent_as_first_message(client, host):
    _, pin = open_game(client, host, new_quiz(client, host))
    with client.websocket_connect(f"/ws/game/{pin}") as ws:
        ws.send_json({"type": "auth", "role": "host", "token": host["token"]})
        assert recv_until(ws, "state:snapshot")["state"] == "lobby"


def test_socket_without_auth_is_closed(client, host):
    _, pin = open_game(client, host, new_quiz(client, host))
    with client.websocket_connect(f"/ws/game/{pin}") as ws:
        ws.send_json({"type": "player:wave"})
        assert ws.receive_json()["type"] == "error"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_broken_json_does_not_drop_connection(client, host):
    _, pin = open_game(client, host, new_quiz(client, host))
    p = join(client, pin, "Ломатель")
    with (
        client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h,
        client.websocket_connect(f"/ws/game/{pin}?token={p['token']}") as ws,
    ):
        recv_until(h, "state:snapshot")
        recv_until(ws, "state:snapshot")
        ws.send_text("это не json")
        assert recv_until(ws, "error")["message"] == "Непонятное сообщение"
        ws.send_json({"type": "player:wave"})
        assert recv_until(h, "lobby:wave")["player_id"] == p["player_id"]


def test_wave_flood_is_throttled(client, host):
    _, pin = open_game(client, host, new_quiz(client, host))
    p = join(client, pin, "Махатель")
    with (
        client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h,
        client.websocket_connect(f"/ws/game/{pin}?token={p['token']}") as ws,
    ):
        recv_until(h, "state:snapshot")
        recv_until(ws, "state:snapshot")
        for _ in range(20):
            ws.send_json({"type": "player:wave"})
        ws.send_json({"type": "player:answer", "questionIndex": 0, "value": {}})  # маркер конца очереди
        recv_until(ws, "error")
        waves = 0
        h.send_json({"type": "host:skip"})  # в лобби ничего не делает — просто ещё одно сообщение
        h.send_json({"type": "no:such"})
        while True:
            msg = h.receive_json()
            if msg["type"] == "error":
                break
            waves += msg["type"] == "lobby:wave"
        assert waves == 1


def test_lobby_reconnects_are_not_reported_as_connection_problems(client, host):
    quiz = new_quiz(client, host)
    sid, pin = open_game(client, host, quiz)
    p = join(client, pin, "Нервный")
    for _ in range(3):  # закрыл и открыл вкладку в лобби
        with client.websocket_connect(f"/ws/game/{pin}?token={p['token']}") as ws:
            recv_until(ws, "state:snapshot")
    right = next(o["id"] for o in quiz["questions"][0]["options"] if o["is_correct"])
    with (
        client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h,
        client.websocket_connect(f"/ws/game/{pin}?token={p['token']}") as ws,
    ):
        recv_until(h, "state:snapshot")
        recv_until(ws, "state:snapshot")
        h.send_json({"type": "host:start"})
        recv_until(ws, "question:start")
        ws.send_json({"type": "player:answer", "questionIndex": 0, "value": {"option_id": right}})
        recv_until(h, "question:reveal")
        h.send_json({"type": "host:next"})
        recv_until(h, "game:finished")
    rep = client.get(f"/api/sessions/{sid}/report", headers=host["headers"]).json()
    assert rep["players"][0]["reconnects"] == 0


def test_stranger_cannot_use_first_message_auth_either(client, host):
    _, pin = open_game(client, host, new_quiz(client, host))
    stranger = register(client, "Чужой")
    with client.websocket_connect(f"/ws/game/{pin}") as ws:
        ws.send_json({"type": "auth", "role": "host", "token": stranger["token"]})
        assert ws.receive_json()["message"] == "Это не ваша игра"
