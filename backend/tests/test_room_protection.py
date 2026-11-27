"""Защита комнаты: модерация во время игры, имена, лимиты на ресурсы одного процесса."""

import pytest
from starlette.websockets import WebSocketDisconnect

from app.game import engine as game
from app.routers import quizzes as quizzes_router
from app.routers.ws import FLOOD_CODE, MAX_MESSAGES_PER_S
from tests.conftest import SAMPLE_QUIZ, game_ws
from tests.test_game import AVATAR, answer, join, open_game, recv_until


def _right(quiz, i=0):
    return next(o["id"] for o in quiz["questions"][i]["options"] if o["is_correct"])


def test_host_can_remove_player_during_question_and_it_closes_when_rest_answered(client, host, quiz):
    sid, pin = open_game(client, host, quiz)
    anya, troll = join(client, pin, "Аня"), join(client, pin, "Тролль")
    with (
        game_ws(client, pin, host["token"], "host") as h,
        game_ws(client, pin, anya["token"]) as pa,
        game_ws(client, pin, troll["token"]) as pt,
    ):
        recv_until(h, "state:snapshot")
        recv_until(pa, "state:snapshot")
        recv_until(pt, "state:snapshot")
        h.send_json({"type": "host:start"})
        recv_until(pa, "question:start")
        answer(pa, 0, {"option_id": _right(quiz)})
        recv_until(pa, "answer:ack")
        # Ждали только тролля — после удаления вопрос закрывается сразу.
        h.send_json({"type": "host:kick", "player_id": troll["player_id"]})
        assert recv_until(pt, "kicked")
        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                pt.receive_json()
        assert closed.value.code == 4001
        reveal = recv_until(h, "question:reveal")
        assert reveal["stats"]["total"] == 1
        assert [p["nickname"] for p in reveal["leaderboard"]] == ["Аня"]
        h.send_json({"type": "host:end"})
        recv_until(h, "game:finished")
    rep = client.get(f"/api/sessions/{sid}/report", headers=host["headers"]).json()
    assert [p["nickname"] for p in rep["players"]] == ["Аня"]
    # Под тем же именем удалённый не вернётся (другая игра того же ведущего не затронута).
    assert client.post(f"/api/sessions/{pin}/join", json={"nickname": "тролль"}).status_code in (403, 404)


def test_host_can_remove_player_on_reveal_screen(client, host, quiz):
    _, pin = open_game(client, host, quiz)
    anya, troll = join(client, pin, "Аня"), join(client, pin, "Тролль")
    with (
        game_ws(client, pin, host["token"], "host") as h,
        game_ws(client, pin, anya["token"]) as pa,
        game_ws(client, pin, troll["token"]) as pt,
    ):
        for ws in (h, pa, pt):
            recv_until(ws, "state:snapshot")
        h.send_json({"type": "host:start"})
        recv_until(pa, "question:start")
        answer(pa, 0, {"option_id": _right(quiz)})
        answer(pt, 0, {"option_id": _right(quiz)})
        recv_until(h, "question:reveal")
        h.send_json({"type": "host:kick", "player_id": troll["player_id"]})
        # Большой экран сразу получает разбор без удалённого игрока.
        reveal = recv_until(h, "question:reveal")
        assert reveal["stats"]["total"] == 1 and len(reveal["leaderboard"]) == 1


@pytest.mark.parametrize(
    "nickname",
    ["Маша\u200b", "\u200bМаша", "Ма\u00adша", "Маша\u202e", "МАША", "Маша\ufeff"],
)
def test_invisible_characters_do_not_make_a_second_masha(client, host, quiz, nickname):
    _, pin = open_game(client, host, quiz)
    join(client, pin, "Маша")
    r = client.post(f"/api/sessions/{pin}/join", json={"nickname": nickname, "avatar": AVATAR})
    assert r.status_code == 409, r.text


def test_nickname_is_cleaned_and_fullwidth_letters_are_normalized(client, host, quiz):
    _, pin = open_game(client, host, quiz)
    r = client.post(f"/api/sessions/{pin}/join", json={"nickname": "  Ｍａｘ\u200b  42 ", "avatar": AVATAR})
    assert r.status_code == 201 and r.json()["nickname"] == "Max 42"
    only_invisible = client.post(f"/api/sessions/{pin}/join", json={"nickname": "\u200b\u202e", "avatar": AVATAR})
    assert only_invisible.status_code == 422


def test_host_has_limited_number_of_open_rooms(client, host, quiz):
    for _ in range(game.MAX_ROOMS_PER_HOST):
        open_game(client, host, quiz)
    r = client.post("/api/sessions", json={"quiz_id": quiz["id"]}, headers=host["headers"])
    assert r.status_code == 409 and "Закройте лишние" in r.json()["detail"]
    # Закрытое лобби освобождает место.
    pin = next(p for p, room in game.manager.rooms.items() if room.host_id == host["user"]["id"])
    with game_ws(client, pin, host["token"], "host") as h:
        recv_until(h, "state:snapshot")
        h.send_json({"type": "host:end"})
        recv_until(h, "error")
    assert client.post("/api/sessions", json={"quiz_id": quiz["id"]}, headers=host["headers"]).status_code == 201


def test_extra_tabs_replace_the_oldest_one(client, host, quiz):
    _, pin = open_game(client, host, quiz)
    me = join(client, pin, "Аня")
    tabs = []
    with game_ws(client, pin, me["token"]) as first:
        recv_until(first, "state:snapshot")
        for _ in range(game.MAX_PLAYER_SOCKETS):
            cm = game_ws(client, pin, me["token"])
            ws = cm.__enter__()
            tabs.append((cm, ws))
            recv_until(ws, "state:snapshot")
        assert "другой вкладке" in recv_until(first, "error")["message"]
        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                first.receive_json()
        assert closed.value.code == game.REPLACED_CODE
        assert len(game.manager.get(pin).players[me["player_id"]].sockets) == game.MAX_PLAYER_SOCKETS
    for cm, _ in tabs:
        cm.__exit__(None, None, None)


def test_message_flood_closes_the_socket(client, host, quiz):
    _, pin = open_game(client, host, quiz)
    me = join(client, pin, "Аня")
    with game_ws(client, pin, me["token"]) as ws:
        recv_until(ws, "state:snapshot")
        for _ in range(MAX_MESSAGES_PER_S + 5):
            ws.send_json({"type": "player:wave"})
        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                ws.receive_json()
        assert closed.value.code == FLOOD_CODE


def test_edit_locks_do_not_accumulate(client, host, quiz):
    for i in range(20):
        client.put(f"/api/quizzes/{1_000_000 + i}", json=SAMPLE_QUIZ, headers=host["headers"])
    client.put(f"/api/quizzes/{quiz['id']}", json=SAMPLE_QUIZ, headers=host["headers"])
    assert len(quizzes_router._edit_locks) == 0
