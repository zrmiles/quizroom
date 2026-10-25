"""Интеграционные тесты игры: REST + WebSocket, ведущий и два игрока."""

from tests.conftest import register

AVATAR = {"shape": "blob", "color": "#FFD23F", "eyes": 2}


def recv_until(ws, kind: str, limit: int = 40) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg
    raise AssertionError(f"Не дождались сообщения {kind}")


def open_game(client, host, quiz) -> tuple[int, str]:
    r = client.post("/api/sessions", json={"quiz_id": quiz["id"]}, headers=host["headers"])
    assert r.status_code == 201, r.text
    return r.json()["id"], r.json()["pin"]


def join(client, pin: str, nickname: str) -> dict:
    r = client.post(f"/api/sessions/{pin}/join", json={"nickname": nickname, "avatar": AVATAR})
    assert r.status_code == 201, r.text
    return r.json()


def answer(ws, index: int, value: dict) -> None:
    ws.send_json({"type": "player:answer", "questionIndex": index, "value": value})


def test_full_game_three_question_types(client, host, quiz):
    session_id, pin = open_game(client, host, quiz)
    assert client.get(f"/api/sessions/{pin}").json()["status"] == "lobby"

    anya = join(client, pin, "Аня")
    timur = join(client, pin, "Тимур")
    assert client.post(f"/api/sessions/{pin}/join", json={"nickname": "аня"}).status_code == 409

    single, number, order = quiz["questions"]
    right = next(o["id"] for o in single["options"] if o["is_correct"])
    wrong = next(o["id"] for o in single["options"] if not o["is_correct"])
    correct_order = [o["id"] for o in order["options"]]

    with (
        client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h,
        client.websocket_connect(f"/ws/game/{pin}?token={anya['token']}") as pa,
        client.websocket_connect(f"/ws/game/{pin}?token={timur['token']}") as pt,
    ):
        assert len(recv_until(h, "state:snapshot")["players"]) == 2
        assert recv_until(pa, "state:snapshot")["you"]["nickname"] == "Аня"
        recv_until(pt, "state:snapshot")

        # Вопрос 1 — один ответ
        h.send_json({"type": "host:start"})
        q = recv_until(pa, "question:start")
        recv_until(pt, "question:start")
        assert q["endsAt"] > q["serverNow"]
        assert "correct" not in str(q["question"])  # правильный ответ не утекает игрокам
        answer(pa, 0, {"option_id": right})
        recv_until(pa, "answer:ack")
        answer(pt, 0, {"option_id": wrong})
        rev = recv_until(h, "question:reveal")
        assert rev["stats"]["correct"] == 1 and rev["correct"]["correct_option_id"] == right
        you = recv_until(pa, "question:reveal")["you"]
        assert you["correct"] and 500 <= you["points"] <= 1000 and you["rank"] == 1
        assert recv_until(pt, "question:reveal")["you"]["points"] == 0

        # Поздний ответ отклоняется
        answer(pt, 0, {"option_id": right})
        assert recv_until(pt, "error")["message"] == "Вопрос уже закрыт"

        # Вопрос 2 — угадай число
        h.send_json({"type": "host:next"})
        q = recv_until(pa, "question:start")["question"]
        recv_until(pt, "question:start")
        assert q["type"] == "number" and (q["min"], q["max"]) == (1900, 2000)
        answer(pa, 1, {"number": 1961})
        answer(pt, 1, {"number": 1990})  # ошибка 29 лет > допуска 20 → 0 очков
        rev = recv_until(h, "question:reveal")
        assert rev["stats"]["exact"] == ["Аня"] and sorted(rev["stats"]["guesses"]) == [1961, 1990]
        assert recv_until(pa, "question:reveal")["you"]["points"] > 1000  # точное попадание ×2
        recv_until(pt, "question:reveal")

        # Вопрос 3 — по порядку, игроки видят перемешанный список
        h.send_json({"type": "host:next"})
        q = recv_until(pa, "question:start")["question"]
        recv_until(pt, "question:start")
        shown = [o["id"] for o in q["options"]]
        assert sorted(shown) == sorted(correct_order) and shown != correct_order
        answer(pa, 2, {"order": correct_order})
        answer(pt, 2, {"order": shown})
        assert recv_until(h, "question:reveal")["isLast"] is True
        recv_until(pa, "question:reveal")
        recv_until(pt, "question:reveal")

        h.send_json({"type": "host:next"})
        final = recv_until(h, "game:finished")
        assert [r["nickname"] for r in final["leaderboard"]] == ["Аня", "Тимур"]
        assert recv_until(pa, "game:finished")["you"]["rank"] == 1
        assert recv_until(pt, "game:finished")["you"]["correct"] == 0

    rep = client.get(f"/api/sessions/{session_id}/report", headers=host["headers"]).json()
    assert rep["session"]["player_count"] == 2
    assert rep["players"][0]["nickname"] == "Аня"
    assert [c["state"] for c in rep["players"][0]["cells"]] == ["fast", "fast", "fast"]
    assert [c["state"] for c in rep["players"][1]["cells"]] == ["wrong", "wrong", "wrong"]
    assert [q["correct_rate"] for q in rep["questions"]] == [0.5, 0.5, 0.5]

    hist = client.get("/api/sessions/history", headers=host["headers"]).json()
    assert hist[0]["id"] == session_id and hist[0]["status"] == "finished" and hist[0]["player_count"] == 2
    # Ни один вопрос не провален большинством — повторять нечего
    assert client.post(f"/api/sessions/{session_id}/retry", headers=host["headers"]).status_code == 400


def test_retry_only_mistakes(client, host, quiz):
    session_id, pin = open_game(client, host, quiz)
    solo = join(client, pin, "Дима")
    single = quiz["questions"][0]
    wrong = next(o["id"] for o in single["options"] if not o["is_correct"])
    with (
        client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h,
        client.websocket_connect(f"/ws/game/{pin}?token={solo['token']}") as p,
    ):
        recv_until(h, "state:snapshot")
        recv_until(p, "state:snapshot")
        h.send_json({"type": "host:start"})
        recv_until(p, "question:start")
        answer(p, 0, {"option_id": wrong})
        recv_until(h, "question:reveal")
        h.send_json({"type": "host:end"})  # ведущий завершает досрочно
        recv_until(h, "game:finished")

    r = client.post(f"/api/sessions/{session_id}/retry", headers=host["headers"])
    assert r.status_code == 201, r.text
    retry_pin = r.json()["pin"]
    info = client.get(f"/api/sessions/{retry_pin}").json()
    assert "работа над ошибками" in info["title"]
    hist = client.get("/api/sessions/history", headers=host["headers"]).json()
    assert hist[0]["parent_session_id"] == session_id and hist[0]["question_count"] == 3


def test_host_cannot_start_without_players(client, host, quiz):
    _, pin = open_game(client, host, quiz)
    with client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h:
        recv_until(h, "state:snapshot")
        h.send_json({"type": "host:start"})
        assert "хотя бы одного" in recv_until(h, "error")["message"]


def test_sockets_reject_strangers(client, host, quiz):
    _, pin = open_game(client, host, quiz)
    stranger = register(client, "Чужой")
    with client.websocket_connect(f"/ws/game/{pin}?role=host&token={stranger['token']}") as ws:
        assert ws.receive_json()["type"] == "error"
    with client.websocket_connect(f"/ws/game/{pin}?token=not-a-token") as ws:
        assert ws.receive_json()["type"] == "error"
    with client.websocket_connect("/ws/game/999999x?token=x") as ws:
        assert ws.receive_json()["message"] == "Комната не найдена"


def test_reconnect_gets_snapshot_with_score(client, host, quiz):
    _, pin = open_game(client, host, quiz)
    me = join(client, pin, "Лиза")
    right = next(o["id"] for o in quiz["questions"][0]["options"] if o["is_correct"])
    with client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h:
        recv_until(h, "state:snapshot")
        with client.websocket_connect(f"/ws/game/{pin}?token={me['token']}") as p:
            recv_until(p, "state:snapshot")
            h.send_json({"type": "host:start"})
            recv_until(p, "question:start")
            answer(p, 0, {"option_id": right})
            recv_until(p, "question:reveal")
        # Игрок «потерял связь» и вернулся
        with client.websocket_connect(f"/ws/game/{pin}?token={me['token']}") as p2:
            snap = recv_until(p2, "state:snapshot")
            assert snap["state"] == "reveal" and snap["you"]["score"] > 0
            assert snap["reveal"]["you"]["correct"] is True


def test_kick_player_in_lobby(client, host, quiz):
    _, pin = open_game(client, host, quiz)
    troll = join(client, pin, "Тролль")
    with (
        client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h,
        client.websocket_connect(f"/ws/game/{pin}?token={troll['token']}") as p,
    ):
        recv_until(h, "state:snapshot")
        recv_until(p, "state:snapshot")
        h.send_json({"type": "host:kick", "player_id": troll["player_id"]})
        assert recv_until(p, "kicked")
        update = recv_until(h, "lobby:update")
        while update["players"]:
            update = recv_until(h, "lobby:update")
    assert client.get(f"/api/sessions/{pin}").json()["player_count"] == 0
