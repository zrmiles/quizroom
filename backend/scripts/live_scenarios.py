"""Сценарные и нагрузочные проверки по запущенному серверу.

Запуск: сначала поднимите API, затем
    PORT=8000 uv run python scripts/live_scenarios.py

Проверяет игру с несколькими игроками, таймер, опоздавших, обрывы связи,
удаление игрока, чужие доступы и 60 одновременных игроков.
"""

import asyncio
import json
import os
import random
import time
import uuid

import httpx
import websockets

PORT = os.environ.get("PORT", "8001")
BASE = f"http://127.0.0.1:{PORT}"
WS = f"ws://127.0.0.1:{PORT}"
results: list[tuple[str, bool, str]] = []


def check(name: str, cond: object, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


class Sock:
    def __init__(self, url: str):
        self.url = url
        self.q: asyncio.Queue = asyncio.Queue()
        self.close_code = None

    async def open(self) -> "Sock":
        self.ws = await websockets.connect(self.url)
        self.task = asyncio.create_task(self._read())
        return self

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                await self.q.put(json.loads(raw))
        except websockets.ConnectionClosed:
            pass
        finally:
            self.close_code = self.ws.close_code
            await self.q.put({"type": "__closed__", "code": self.ws.close_code})

    async def wait(self, kind: str, timeout: float = 10) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(kind)
            m = await asyncio.wait_for(self.q.get(), left)
            if m["type"] == kind:
                return m
            if m["type"] == "__closed__" and kind != "__closed__":
                raise ConnectionError(f"закрыт ({m['code']}) в ожидании {kind}")

    def drain(self) -> None:
        while not self.q.empty():
            self.q.get_nowait()

    async def send(self, **m) -> None:
        await self.ws.send(json.dumps(m))

    async def close(self) -> None:
        await self.ws.close()
        await asyncio.sleep(0.05)


QUIZ = {
    "title": "Сценарии",
    "questions": [
        {
            "type": "single",
            "text": "Самая большая планета?",
            "time_limit": 5,
            "options": [{"text": "Юпитер", "is_correct": True}, {"text": "Сатурн"}, {"text": "Нептун"}],
        },
        {
            "type": "number",
            "text": "Год полёта Гагарина?",
            "time_limit": 5,
            "number_answer": 1961,
            "number_min": 1900,
            "number_max": 2000,
            "number_tolerance": 20,
            "number_exact_bonus": True,
        },
        {
            "type": "order",
            "text": "По размеру",
            "time_limit": 5,
            "options": [{"text": "Юпитер"}, {"text": "Нептун"}, {"text": "Земля"}, {"text": "Марс"}],
        },
    ],
}


async def new_host(http: httpx.AsyncClient) -> dict:
    email = f"e2e-{uuid.uuid4().hex[:8]}@example.com"
    r = await http.post("/api/auth/register", json={"email": email, "username": "Ведущий", "password": "password123"})
    tok = r.json()["access_token"]
    return {"token": tok, "h": {"Authorization": f"Bearer {tok}"}}


async def new_game(http, host, quiz=QUIZ) -> tuple[dict, int, str]:
    q = (await http.post("/api/quizzes", json=quiz, headers=host["h"])).json()
    s = (await http.post("/api/sessions", json={"quiz_id": q["id"]}, headers=host["h"])).json()
    return q, s["id"], s["pin"]


async def join(http, pin, nick, color="#FF7A59") -> dict:
    r = await http.post(
        f"/api/sessions/{pin}/join", json={"nickname": nick, "avatar": {"shape": "round", "color": color, "eyes": 2}}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def player_sock(pin, token) -> Sock:
    s = await Sock(f"{WS}/ws/game/{pin}?token={token}").open()
    await s.wait("state:snapshot")
    return s


async def host_sock(pin, token) -> Sock:
    s = await Sock(f"{WS}/ws/game/{pin}?role=host&token={token}").open()
    await s.wait("state:snapshot")
    return s


# ---------------------------------------------------------------- сценарии


async def scenario_full_game(http):
    print("\n== 1. Пять игроков: таймер, опоздавший, ошибки ввода, обрывы связи")
    host = await new_host(http)
    quiz, sid, pin = await new_game(http, host)
    single, number, order = quiz["questions"]
    right = next(o["id"] for o in single["options"] if o["is_correct"])
    wrong = next(o["id"] for o in single["options"] if not o["is_correct"])

    tickets = [await join(http, pin, n) for n in ["Аня", "Тимур", "Маша", "Дима", "Молчун"]]
    h = await host_sock(pin, host["token"])
    ps = [await player_sock(pin, t["token"]) for t in tickets]
    anya, timur, masha, dima, silent = ps

    await h.send(type="host:start")
    starts = [await p.wait("question:start") for p in ps]
    check("вопрос пришёл всем игрокам", len(starts) == 5)
    check("таймер 5 с от сервера", starts[0]["endsAt"] - starts[0]["serverNow"] == 5000)
    t0 = time.monotonic()
    for p in (anya, timur, masha):
        await p.send(type="player:answer", questionIndex=0, value={"option_id": right})
    await dima.send(type="player:answer", questionIndex=0, value={"option_id": wrong})
    rev = await h.wait("question:reveal", timeout=8)
    waited = time.monotonic() - t0
    check("вопрос закрылся по таймеру, не раньше и не сильно позже", 4.3 < waited < 6.5, f"{waited:.2f} с")
    check(
        "статистика: ответили 4 из 5, верно 3",
        (rev["stats"]["answered"], rev["stats"]["total"], rev["stats"]["correct"]) == (4, 5, 3),
    )
    sr = await silent.wait("question:reveal")
    check("молчун видит «не ответил» и 0 очков", sr["you"]["answered"] is False and sr["you"]["points"] == 0)
    for p in (anya, timur, masha, dima):
        await p.wait("question:reveal")

    # Вопрос 2 — опоздавший и ошибки ввода
    await h.send(type="host:next")
    for p in ps:
        await p.wait("question:start")
    late_t = await join(http, pin, "Опоздавший", "#5BD9A0")
    late = await Sock(f"{WS}/ws/game/{pin}?token={late_t['token']}").open()
    snap = await late.wait("state:snapshot")
    check("опоздавший сразу получает текущий вопрос", snap["state"] == "question" and snap["question"]["index"] == 1)
    for bad, label in [
        ({"number": "1961"}, "строка"),
        ({"number": 3000}, "вне шкалы"),
        ({"option_id": 1}, "чужой формат"),
    ]:
        await late.send(type="player:answer", questionIndex=1, value=bad)
        err = await late.wait("error")
        check(f"неверный ответ ({label}) отклонён с понятной ошибкой", bool(err["message"]), err["message"])
    await late.send(type="player:answer", questionIndex=1, value={"number": 1961})
    await late.wait("answer:ack")
    await late.send(type="player:answer", questionIndex=1, value={"number": 1961})
    await late.wait("answer:ack")
    for p, v in zip((anya, timur, masha, dima), (1961, 1958, 1990, 1940), strict=True):
        await p.send(type="player:answer", questionIndex=1, value={"number": v})
    rev = await h.wait("question:reveal", timeout=8)
    check("гистограмма содержит 5 догадок", len(rev["stats"]["guesses"]) == 5, str(rev["stats"]["guesses"]))
    check("точное попадание у Ани и опоздавшего", sorted(rev["stats"]["exact"]) == ["Аня", "Опоздавший"])
    lr = await late.wait("question:reveal")
    check("повторный ответ не удвоил очки", lr["you"]["points"] == lr["you"]["score"], f"{lr['you']}")
    ps.append(late)
    for p in ps[:-1]:
        await p.wait("question:reveal")

    # Вопрос 3 — Маша теряет связь и возвращается; ведущий тоже
    await h.send(type="host:next")
    current = None
    for p in ps:
        current = (await p.wait("question:start"))["question"]
    by_text = {o["text"]: o["id"] for o in current["options"]}
    correct_order = [by_text[o["text"]] for o in order["options"]]
    score_before = lr["you"]["score"]
    await masha.close()
    masha = await Sock(f"{WS}/ws/game/{pin}?token={tickets[2]['token']}").open()
    snap = await masha.wait("state:snapshot")
    check(
        "Маша после обрыва видит тот же вопрос и может ответить",
        snap["state"] == "question" and snap["youAnswered"] is False,
    )
    for p in (anya, masha, late):
        await p.send(type="player:answer", questionIndex=2, value={"order": correct_order})
    await timur.send(type="player:answer", questionIndex=2, value={"order": correct_order[:2]})
    err = await timur.wait("error")
    check("неполный порядок отклонён", "все элементы" in err["message"], err["message"])
    await timur.send(type="player:answer", questionIndex=2, value={"order": list(reversed(correct_order))})
    await dima.send(type="player:answer", questionIndex=2, value={"order": correct_order})
    await h.wait("question:reveal", timeout=8)
    await h.close()
    h = await Sock(f"{WS}/ws/game/{pin}?role=host&token={host['token']}").open()
    snap = await h.wait("state:snapshot")
    check("ведущий после обрыва вернулся на разбор", snap["state"] == "reveal" and snap["reveal"]["isLast"] is True)
    await h.send(type="host:next")
    fin = await h.wait("game:finished")
    board = fin["leaderboard"]
    check(
        "таблица отсортирована по очкам",
        [r["score"] for r in board] == sorted((r["score"] for r in board), reverse=True),
    )
    expected_ranks = [next(i + 1 for i, entry in enumerate(board) if entry["score"] == r["score"]) for r in board]
    check("места учитывают равные очки", [r["rank"] for r in board] == expected_ranks)
    check("у молчуна 0 очков и последнее место", board[-1]["nickname"] == "Молчун" and board[-1]["score"] == 0)
    you = (await late.wait("game:finished"))["you"]
    check(
        "опоздавший видит своё место и счёт",
        you["players"] == 6
        and you["score"] > score_before
        and you["score"] == next(r["score"] for r in board if r["nickname"] == "Опоздавший"),
    )

    rep = (await http.get(f"/api/sessions/{sid}/report", headers=host["h"])).json()
    late_row = next(p for p in rep["players"] if p["nickname"] == "Опоздавший")
    silent_row = next(p for p in rep["players"] if p["nickname"] == "Молчун")
    check("в отчёте у опоздавшего пропущен 1-й вопрос", late_row["cells"][0]["state"] == "none")
    check("в отчёте у молчуна все ячейки пустые", all(c["state"] == "none" for c in silent_row["cells"]))
    check("переподключение Маши учтено", next(p for p in rep["players"] if p["nickname"] == "Маша")["reconnects"] == 1)
    check("«дошли до конца» = 5 (кроме молчуна)", rep["summary"]["finished_count"] == 5, str(rep["summary"]))
    for s in [h, *ps]:
        await s.close()
    return host, sid, pin


async def scenario_kick_and_security(http, finished_pin):
    print("\n== 2. Удаление игрока и чужие доступы")
    host = await new_host(http)
    _, sid, pin = await new_game(http, host)
    troll = await join(http, pin, "Тролль")
    h = await host_sock(pin, host["token"])
    p = await player_sock(pin, troll["token"])
    await h.send(type="host:kick", player_id=troll["player_id"])
    await p.wait("kicked")
    closed = await p.wait("__closed__")
    check("удалённый игрок отключён с кодом 4001", closed["code"] == 4001)
    again = await Sock(f"{WS}/ws/game/{pin}?token={troll['token']}").open()
    err = await again.wait("error")
    check("удалённый не может вернуться со старым токеном", "заново" in err["message"])
    r = await http.post(f"/api/sessions/{pin}/join", json={"nickname": "Тролль"})
    check("но может зайти заново под тем же именем", r.status_code == 201)

    stranger = await new_host(http)
    s = await Sock(f"{WS}/ws/game/{pin}?role=host&token={stranger['token']}").open()
    await s.wait("error")
    check("чужой ведущий не подключится к комнате", (await s.wait("__closed__"))["code"] == 4403)
    r = await http.get(f"/api/sessions/{sid}/report", headers=stranger["h"])
    check("чужой отчёт недоступен", r.status_code == 404)
    r = await http.post(f"/api/sessions/{pin}/join", json={"nickname": "x", "avatar": {"color": "#000000"}})
    check("неизвестный цвет аватара отклонён", r.status_code == 422)
    r = await http.post(f"/api/sessions/{pin}/join", json={"nickname": "Очень-длинное-имя-игрока"})
    check("слишком длинное имя отклонено", r.status_code == 422)
    r = await http.post(f"/api/sessions/{pin}/join", json={"nickname": "   "})
    check("имя из пробелов отклонено", r.status_code == 422)
    r = await http.post(f"/api/sessions/{finished_pin}/join", json={"nickname": "Поздно"})
    check("в закончившуюся игру не войти", r.status_code == 404)
    r = await http.post("/api/quizzes", json={"title": "Пустая"}, headers=host["h"])
    r2 = await http.post("/api/sessions", json={"quiz_id": r.json()["id"]}, headers=host["h"])
    check("пустую викторину нельзя запустить", r2.status_code == 400, r2.json().get("detail", ""))
    await h.send(type="host:start")
    await h.wait("question:start")
    await h.send(type="host:kick", player_id=123456)
    err = await h.wait("error")
    check("во время игры удалять нельзя", "лобби" in err["message"])
    await h.send(type="host:skip")
    rev = await h.wait("question:reveal")
    check("ведущий может закрыть вопрос досрочно", rev["stats"]["answered"] == 0)
    await h.send(type="host:start")
    check("повторный старт отклонён", "уже идёт" in (await h.wait("error"))["message"])
    await h.send(type="host:end")
    await h.wait("game:finished")
    for x in (h, again):
        await x.close()


async def scenario_load(http, n=60):
    print(f"\n== 3. Нагрузка: {n} игроков отвечают одновременно")
    host = await new_host(http)
    quiz, sid, pin = await new_game(http, host)
    right = next(o["id"] for o in quiz["questions"][0]["options"] if o["is_correct"])
    t = time.monotonic()
    tickets = await asyncio.gather(*(join(http, pin, f"Игрок{i}", "#9B8CFF") for i in range(n)))
    check(f"{n} игроков вошли", len(tickets) == n, f"{time.monotonic() - t:.2f} с")
    h = await host_sock(pin, host["token"])
    ps = await asyncio.gather(*(player_sock(pin, tk["token"]) for tk in tickets))
    await h.send(type="host:start")
    await asyncio.gather(*(p.wait("question:start") for p in ps))

    async def answer(p):
        await asyncio.sleep(random.random())
        await p.send(type="player:answer", questionIndex=0, value={"option_id": right})

    t = time.monotonic()
    await asyncio.gather(*(answer(p) for p in ps))
    rev = await h.wait("question:reveal", timeout=10)
    lag = time.monotonic() - t
    check("все ответы учтены", rev["stats"]["answered"] == n)
    check("разбор приходит сразу после последнего ответа", lag < 2.0, f"{lag:.2f} с")
    got = await asyncio.gather(*(p.wait("question:reveal") for p in ps))
    check("разбор получили все игроки", len(got) == n)
    scores = sorted((g["you"]["score"] for g in got), reverse=True)
    check("быстрые получили больше очков", scores[0] > scores[-1], f"{scores[0]}…{scores[-1]}")
    await h.send(type="host:end")
    await h.wait("game:finished")
    await asyncio.gather(*(p.close() for p in ps))
    await h.close()


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as http:
        _, _, pin = await scenario_full_game(http)
        await scenario_kick_and_security(http, pin)
        await scenario_load(http)
    bad = [r for r in results if not r[1]]
    print(f"\nИтог: {len(results) - len(bad)} из {len(results)} проверок прошли")
    for name, _, detail in bad:
        print("  FAIL:", name, detail)


asyncio.run(main())
