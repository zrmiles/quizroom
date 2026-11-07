# ---------- R05, R22: отчёт только по тому, что реально показывали ----------


def _play_first_question_then_end(client, host, quiz, players_answer):
    from tests.test_game import answer, join, open_game, recv_until

    sid, pin = open_game(client, host, quiz)
    joined = {nick: join(client, pin, nick) for nick in players_answer}
    with client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h:
        recv_until(h, "state:snapshot")
        sockets = {}
        for nick, info in joined.items():
            sockets[nick] = client.websocket_connect(f"/ws/game/{pin}?token={info['token']}").__enter__()
            recv_until(sockets[nick], "state:snapshot")
        h.send_json({"type": "host:start"})
        for nick, value in players_answer.items():
            recv_until(sockets[nick], "question:start")
            if value is not None:
                answer(sockets[nick], 0, value)
                recv_until(sockets[nick], "answer:ack")
        late = join(client, pin, "Опоздавший")  # вошёл, когда первый вопрос уже шёл
        h.send_json({"type": "host:skip"})
        recv_until(h, "question:reveal")
        h.send_json({"type": "host:end"})
        recv_until(h, "game:finished")
        for ws in sockets.values():
            ws.__exit__(None, None, None)
    return sid, late


def test_early_finish_report_ignores_unshown_questions(client, host, quiz):
    single = quiz["questions"][0]
    right = next(o["id"] for o in single["options"] if o["is_correct"])
    wrong = next(o["id"] for o in single["options"] if not o["is_correct"])
    sid, _ = _play_first_question_then_end(
        client, host, quiz, {"Аня": {"option_id": right}, "Борис": {"option_id": wrong}, "Вика": None}
    )
    rep = client.get(f"/api/sessions/{sid}/report", headers=host["headers"]).json()
    s = rep["summary"]
    assert s["ended_early"] is True and s["shown_count"] == 1
    assert [q["shown"] for q in rep["questions"]] == [True, False, False]
    # Верно ответила одна из четырёх: опоздавший вошёл, пока вопрос шёл, и тоже мог ответить.
    assert [q["correct_rate"] for q in rep["questions"]] == [0.25, None, None]
    assert s["avg_correct_rate"] == 0.25 and s["hardest_index"] == 0
    assert s["retry_count"] == 1 and s["finished_count"] == 2
    rows = {p["nickname"]: p for p in rep["players"]}
    assert [c["state"] for c in rows["Вика"]["cells"]] == ["none", "unshown", "unshown"]
    assert rows["Вика"]["asked"] == 1 and rows["Вика"]["skipped"] == 1


def test_player_who_joined_mid_question_counts_in_it(client, host, quiz):
    single = quiz["questions"][0]
    right = next(o["id"] for o in single["options"] if o["is_correct"])
    sid, _ = _play_first_question_then_end(client, host, quiz, {"Аня": {"option_id": right}, "Вика": None})
    rep = client.get(f"/api/sessions/{sid}/report", headers=host["headers"]).json()
    late = next(p for p in rep["players"] if p["nickname"] == "Опоздавший")
    # Вошёл во время вопроса — мог ответить, значит «нет ответа», а не «не участвовал».
    assert late["cells"][0]["state"] == "none"
    assert rep["questions"][0]["eligible"] == 3


def test_late_player_is_absent_not_wrong(client, host, quiz):
    from tests.test_game import answer, join, open_game, recv_until

    single = quiz["questions"][0]
    right = next(o["id"] for o in single["options"] if o["is_correct"])
    sid, pin = open_game(client, host, quiz)
    first = join(client, pin, "Аня")
    with (
        client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h,
        client.websocket_connect(f"/ws/game/{pin}?token={first['token']}") as p,
    ):
        recv_until(h, "state:snapshot")
        recv_until(p, "state:snapshot")
        h.send_json({"type": "host:start"})
        recv_until(p, "question:start")
        answer(p, 0, {"option_id": right})
        recv_until(h, "question:reveal")
        join(client, pin, "Опоздавший")  # вошёл на разборе первого вопроса
        h.send_json({"type": "host:end"})
        recv_until(h, "game:finished")
    rep = client.get(f"/api/sessions/{sid}/report", headers=host["headers"]).json()
    late = next(r for r in rep["players"] if r["nickname"] == "Опоздавший")
    assert late["cells"][0]["state"] == "absent" and late["skipped"] == 0
    assert rep["questions"][0]["correct_rate"] == 1.0  # опоздавший не тянет вниз долю верных


def test_retry_of_empty_game_is_refused(client, host, quiz):
    from tests.test_game import open_game, recv_until

    sid, pin = open_game(client, host, quiz)
    with client.websocket_connect(f"/ws/game/{pin}?role=host&token={host['token']}") as h:
        recv_until(h, "state:snapshot")
        h.send_json({"type": "host:end"})
        recv_until(h, "game:finished")
    rep = client.get(f"/api/sessions/{sid}/report", headers=host["headers"]).json()
    assert rep["summary"]["retry_count"] == 0 and rep["summary"]["avg_correct_rate"] is None
    r = client.post(f"/api/sessions/{sid}/retry", headers=host["headers"])
    assert r.status_code == 400 and "не было участников" in r.json()["detail"]


def test_retry_does_not_carry_report_marks(client, host, quiz):
    from app.models import GameSession
    from tests.test_game import answer, join, open_game, recv_until

    single = quiz["questions"][0]
    wrong = next(o["id"] for o in single["options"] if not o["is_correct"])
    sid, pin = open_game(client, host, quiz)
    solo = join(client, pin, "Дима")
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
        h.send_json({"type": "host:end"})
        recv_until(h, "game:finished")
    new_id = client.post(f"/api/sessions/{sid}/retry", headers=host["headers"]).json()["id"]

    async def snapshot():
        from app.db import SessionLocal

        async with SessionLocal() as db:
            return (await db.get(GameSession, new_id)).snapshot

    snap = client.portal.call(snapshot)
    assert len(snap) == 1 and not any(k in snap[0] for k in ("eligible", "shown"))
