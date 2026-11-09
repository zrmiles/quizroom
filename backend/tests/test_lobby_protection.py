"""Защита лобби (R01 аудита готовности от 5 ноября): закрытый вход, удалённые имена, лимиты."""

from unittest.mock import patch

from app import rate_limits
from tests.test_audit_fixes import new_quiz
from tests.test_game import join, open_game, recv_until

AVATAR = {"shape": "blob", "color": "#FFD23F", "eyes": 2}


def _try_join(client, pin, nickname):
    return client.post(f"/api/sessions/{pin}/join", json={"nickname": nickname, "avatar": AVATAR})


def test_host_can_close_and_reopen_entry(client, host):
    _, pin = open_game(client, host, new_quiz(client, host))
    first = join(client, pin, "Аня")
    with client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h:
        assert recv_until(h, "state:snapshot")["locked"] is False
        h.send_json({"type": "host:lock"})
        assert recv_until(h, "lobby:update")["locked"] is True
        r = _try_join(client, pin, "Тролль")
        assert r.status_code == 403 and "закрыл вход" in r.json()["detail"]
        assert client.get(f"/api/sessions/{pin}").json()["accepting"] is False
        # Уже вошедший игрок переподключается как обычно.
        with client.websocket_connect(f"/ws/game/{pin}?token={first['token']}") as p:
            assert recv_until(p, "state:snapshot")["you"]["nickname"] == "Аня"
        h.send_json({"type": "host:unlock"})
        update = recv_until(h, "lobby:update")
        while update["locked"]:
            update = recv_until(h, "lobby:update")
    assert _try_join(client, pin, "Борис").status_code == 201


def test_kicked_nickname_cannot_come_back(client, host):
    _, pin = open_game(client, host, new_quiz(client, host))
    troll = join(client, pin, "Тролль")
    with client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h:
        recv_until(h, "state:snapshot")
        h.send_json({"type": "host:kick", "player_id": troll["player_id"]})
        update = recv_until(h, "lobby:update")
        while update["players"]:
            update = recv_until(h, "lobby:update")
    r = _try_join(client, pin, "  тРОЛЛЬ ".strip())
    assert r.status_code == 403 and "удалил" in r.json()["detail"]
    assert _try_join(client, pin, "Аня").status_code == 201


def test_wrong_pins_are_limited_but_right_ones_are_not(client, host):
    _, pin = open_game(client, host, new_quiz(client, host))
    for _ in range(50):  # проверка существующего кода лимит не тратит
        assert client.get(f"/api/sessions/{pin}").status_code == 200
    wrong = "000000" if pin != "000000" else "000001"
    for _ in range(rate_limits.LIMITS["pin_miss"]):
        assert client.get(f"/api/sessions/{wrong}").status_code == 404
    r = client.get(f"/api/sessions/{pin}")
    assert r.status_code == 429 and "неверных кодов" in r.json()["detail"]
    assert _try_join(client, pin, "Перебор").status_code == 429


def test_joins_from_one_address_are_limited(client, host):
    _, pin = open_game(client, host, new_quiz(client, host))
    with patch.dict(rate_limits.LIMITS, {"join": 3}):
        for i in range(3):
            assert _try_join(client, pin, f"Бот{i}").status_code == 201
        r = _try_join(client, pin, "Бот3")
    assert r.status_code == 429 and r.headers["Retry-After"] == "60"
