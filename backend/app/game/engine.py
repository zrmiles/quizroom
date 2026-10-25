"""Игровой движок: комнаты в памяти процесса.

Сервер — единственный источник истины: он хранит состояние комнаты, сам закрывает
вопрос по таймеру и считает очки. Клиент лишь рисует таймер от `endsAt`.

Ограничение MVP: состояние живёт в памяти одного процесса API (один воркер uvicorn).
Для нескольких воркеров состояние переезжает в Redis — см. docs/PLAN.md.
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket
from sqlalchemy import delete, select

from app.config import settings
from app.db import SessionLocal
from app.game.scoring import score
from app.models import GameSession, Player, PlayerAnswer

log = logging.getLogger("quizroom.game")

LOBBY, QUESTION, REVEAL, FINISHED = "lobby", "question", "reveal", "finished"


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class PlayerState:
    id: int
    nickname: str
    avatar: dict[str, Any]
    token: str
    score: int = 0
    connections: int = 0
    sockets: set[WebSocket] = field(default_factory=set)
    answers: dict[int, dict[str, Any]] = field(default_factory=dict)

    @property
    def connected(self) -> bool:
        return bool(self.sockets)

    @property
    def reconnects(self) -> int:
        return max(0, self.connections - 1)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nickname": self.nickname,
            "avatar": self.avatar,
            "connected": self.connected,
            "score": self.score,
        }


class Room:
    def __init__(self, session_id: int, pin: str, host_id: int, title: str, questions: list[dict[str, Any]]):
        self.session_id = session_id
        self.pin = pin
        self.host_id = host_id
        self.title = title
        self.questions = questions
        self.state = LOBBY
        self.index = -1
        self.started_at_ms = 0
        self.ends_at_ms = 0
        self.players: dict[int, PlayerState] = {}
        self.host_sockets: set[WebSocket] = set()
        self.timer: asyncio.Task[None] | None = None
        self.lock = asyncio.Lock()
        # Для «по порядку» игроки видят элементы перемешанными — одинаково для всех.
        self.shuffles: dict[int, list[dict[str, Any]]] = {}
        for i, q in enumerate(questions):
            if q["type"] == "order":
                self.shuffles[i] = _shuffle_not_identity([{"id": o["id"], "text": o["text"]} for o in q["options"]])

    # ---------- игроки и сокеты ----------

    def add_player(self, player_id: int, nickname: str, avatar: dict[str, Any], token: str) -> PlayerState:
        st = PlayerState(id=player_id, nickname=nickname, avatar=avatar, token=token)
        self.players[player_id] = st
        return st

    def nickname_taken(self, nickname: str) -> bool:
        low = nickname.casefold()
        return any(p.nickname.casefold() == low for p in self.players.values())

    def player_by_token(self, token: str) -> PlayerState | None:
        return next((p for p in self.players.values() if p.token == token), None)

    def attach(self, ws: WebSocket, player: PlayerState | None) -> None:
        if player is None:
            self.host_sockets.add(ws)
        else:
            player.sockets.add(ws)
            player.connections += 1

    def detach(self, ws: WebSocket, player: PlayerState | None) -> None:
        if player is None:
            self.host_sockets.discard(ws)
        else:
            player.sockets.discard(ws)

    async def _send(self, ws: WebSocket, msg: dict[str, Any]) -> None:
        try:
            await ws.send_json(msg)
        except Exception:  # сокет уже закрыт — игрок переподключится и получит снапшот
            pass

    async def _to_hosts(self, msg: dict[str, Any]) -> None:
        for ws in list(self.host_sockets):
            await self._send(ws, msg)

    async def _to_player(self, p: PlayerState, msg: dict[str, Any]) -> None:
        for ws in list(p.sockets):
            await self._send(ws, msg)

    async def _to_players(self, msg: dict[str, Any]) -> None:
        for p in list(self.players.values()):
            await self._to_player(p, msg)

    async def broadcast_lobby(self) -> None:
        msg = {"type": "lobby:update", "players": [p.public() for p in self.players.values()]}
        await self._to_hosts(msg)
        await self._to_players({"type": "lobby:update", "playerCount": len(self.players)})

    # ---------- представления ----------

    def public_question(self, i: int) -> dict[str, Any]:
        q = self.questions[i]
        options = self.shuffles.get(i) or [{"id": o["id"], "text": o["text"]} for o in q["options"]]
        data = {
            "index": i,
            "total": len(self.questions),
            "type": q["type"],
            "text": q["text"],
            "time_limit": q["time_limit"],
            "options": options,
        }
        if q["type"] == "number":
            data.update(min=q["min"], max=q["max"])
        return data

    def correct_info(self, i: int) -> dict[str, Any]:
        q = self.questions[i]
        if q["type"] == "single":
            return {"correct_option_id": q["correct_option_id"]}
        if q["type"] == "number":
            return {"answer": q["answer"], "tolerance": q["tolerance"], "exact_bonus": q["exact_bonus"]}
        return {"correct_order": q["correct_order"]}

    def leaderboard(self) -> list[dict[str, Any]]:
        ranked = sorted(self.players.values(), key=lambda p: (-p.score, p.nickname.casefold()))
        return [{**p.public(), "rank": i + 1} for i, p in enumerate(ranked)]

    def _rank_of(self, player_id: int) -> int:
        return next(r["rank"] for r in self.leaderboard() if r["id"] == player_id)

    def stats(self, i: int) -> dict[str, Any]:
        q = self.questions[i]
        answers = [p.answers[i] for p in self.players.values() if i in p.answers]
        data: dict[str, Any] = {
            "answered": len(answers),
            "total": len(self.players),
            "correct": sum(1 for a in answers if a["correct"]),
        }
        if q["type"] == "single":
            counts = {o["id"]: 0 for o in q["options"]}
            for a in answers:
                counts[a["value"]["option_id"]] += 1
            data["counts"] = [{"option_id": k, "count": v} for k, v in counts.items()]
        elif q["type"] == "number":
            guesses = [a["value"]["number"] for a in answers]
            data["guesses"] = guesses
            data["average"] = round(sum(guesses) / len(guesses), 1) if guesses else None
            exact = [p.nickname for p in self.players.values() if i in p.answers and p.answers[i]["exact"]]
            data["exact"] = exact
        return data

    def _reveal_for_host(self, i: int) -> dict[str, Any]:
        return {
            "type": "question:reveal",
            "question": self.public_question(i),
            "correct": self.correct_info(i),
            "stats": self.stats(i),
            "leaderboard": self.leaderboard()[:10],
            "isLast": i == len(self.questions) - 1,
        }

    def _reveal_for_player(self, i: int, p: PlayerState) -> dict[str, Any]:
        a = p.answers.get(i)
        return {
            "type": "question:reveal",
            "question": self.public_question(i),
            "correct": self.correct_info(i),
            "you": {
                "answered": a is not None,
                "correct": bool(a and a["correct"]),
                "points": a["points"] if a else 0,
                "exact": bool(a and a["exact"]),
                "score": p.score,
                "rank": self._rank_of(p.id),
            },
            "isLast": i == len(self.questions) - 1,
        }

    def _final_for_host(self) -> dict[str, Any]:
        return {"type": "game:finished", "sessionId": self.session_id, "leaderboard": self.leaderboard()}

    def _final_for_player(self, p: PlayerState) -> dict[str, Any]:
        board = self.leaderboard()
        correct = sum(1 for a in p.answers.values() if a["correct"])
        return {
            "type": "game:finished",
            "leaderboard": board[:3],
            "you": {
                "score": p.score,
                "rank": self._rank_of(p.id),
                "correct": correct,
                "total": len(self.questions),
                "players": len(board),
            },
        }

    def snapshot(self, player: PlayerState | None) -> dict[str, Any]:
        snap: dict[str, Any] = {
            "type": "state:snapshot",
            "state": self.state,
            "pin": self.pin,
            "title": self.title,
            "serverNow": now_ms(),
            "playerCount": len(self.players),
            "questionCount": len(self.questions),
        }
        if player is None:
            snap["players"] = [p.public() for p in self.players.values()]
        else:
            snap["you"] = {**player.public(), "rank": self._rank_of(player.id)}
        if self.state == QUESTION:
            snap["question"] = self.public_question(self.index)
            snap["endsAt"] = self.ends_at_ms
            snap["answered"] = sum(1 for p in self.players.values() if self.index in p.answers)
            if player is not None:
                snap["youAnswered"] = self.index in player.answers
        elif self.state == REVEAL:
            snap["reveal"] = (
                self._reveal_for_host(self.index) if player is None else self._reveal_for_player(self.index, player)
            )
        elif self.state == FINISHED:
            snap["final"] = self._final_for_host() if player is None else self._final_for_player(player)
        return snap

    # ---------- команды ----------

    async def handle(self, ws: WebSocket, player: PlayerState | None, msg: dict[str, Any]) -> None:
        kind = msg.get("type") if isinstance(msg, dict) else None
        async with self.lock:
            try:
                if player is None:
                    await self._handle_host(kind, msg)
                else:
                    await self._handle_player(player, kind, msg)
            except GameError as e:
                await self._send(ws, {"type": "error", "message": str(e)})

    async def _handle_host(self, kind: Any, msg: dict[str, Any]) -> None:
        if kind == "host:start":
            if self.state != LOBBY:
                raise GameError("Игра уже идёт")
            if not self.players:
                raise GameError("Подождите хотя бы одного игрока")
            await self._mark_started()
            await self._start_question(0)
        elif kind == "host:next":
            if self.state != REVEAL:
                raise GameError("Сначала дождитесь конца вопроса")
            if self.index + 1 < len(self.questions):
                await self._start_question(self.index + 1)
            else:
                await self._finish()
        elif kind == "host:skip":
            if self.state == QUESTION:
                await self._close_question()
        elif kind == "host:end":
            if self.state != FINISHED:
                await self._finish()
        elif kind == "host:kick":
            await self._kick(msg.get("player_id"))
        else:
            raise GameError("Неизвестная команда")

    async def _handle_player(self, p: PlayerState, kind: Any, msg: dict[str, Any]) -> None:
        if kind == "player:answer":
            await self._submit(p, msg.get("questionIndex"), msg.get("value"))
        elif kind == "player:wave":
            wave = {"type": "lobby:wave", "player_id": p.id}
            await self._to_hosts(wave)
            await self._to_players(wave)
        else:
            raise GameError("Неизвестная команда")

    async def _start_question(self, i: int) -> None:
        self._cancel_timer()
        self.index = i
        self.state = QUESTION
        self.started_at_ms = now_ms()
        self.ends_at_ms = self.started_at_ms + self.questions[i]["time_limit"] * 1000
        msg = {
            "type": "question:start",
            "question": self.public_question(i),
            "endsAt": self.ends_at_ms,
            "serverNow": self.started_at_ms,
        }
        await self._to_hosts({**msg, "answered": 0, "total": len(self.players)})
        await self._to_players(msg)
        delay = (self.ends_at_ms + settings.answer_grace_ms - now_ms()) / 1000
        self.timer = asyncio.create_task(self._close_after(i, delay))

    async def _close_after(self, i: int, delay_s: float) -> None:
        await asyncio.sleep(max(0.0, delay_s))
        async with self.lock:
            if self.state == QUESTION and self.index == i:
                await self._close_question()

    def _cancel_timer(self) -> None:
        if self.timer and self.timer is not asyncio.current_task() and not self.timer.done():
            self.timer.cancel()
        self.timer = None

    async def _submit(self, p: PlayerState, question_index: Any, value: Any) -> None:
        if self.state != QUESTION or question_index != self.index:
            raise GameError("Вопрос уже закрыт")
        now = now_ms()
        if now > self.ends_at_ms + settings.answer_grace_ms:
            raise GameError("Время вышло")
        if self.index in p.answers:
            await self._to_player(p, {"type": "answer:ack", "questionIndex": self.index})
            return
        q = self.questions[self.index]
        response_ms = now - self.started_at_ms
        try:
            correct, points = score(q, value, response_ms)
        except (ValueError, KeyError, TypeError) as e:
            raise GameError(str(e) or "Неверный ответ") from e
        exact = q["type"] == "number" and abs(float(value["number"]) - q["answer"]) < 1e-9
        p.answers[self.index] = {
            "value": value,
            "correct": correct,
            "points": points,
            "ms": response_ms,
            "exact": exact,
        }
        p.score += points
        await self._to_player(p, {"type": "answer:ack", "questionIndex": self.index})
        answered = sum(1 for pl in self.players.values() if self.index in pl.answers)
        await self._to_hosts({"type": "question:progress", "answered": answered, "total": len(self.players)})
        waiting = [pl for pl in self.players.values() if pl.connected and self.index not in pl.answers]
        if not waiting:
            await self._close_question()

    async def after_disconnect(self) -> None:
        """Если ушёл единственный, кого ждали, — не держим остальных до конца таймера."""
        async with self.lock:
            if self.state != QUESTION:
                return
            connected = [p for p in self.players.values() if p.connected]
            if connected and all(self.index in p.answers for p in connected):
                await self._close_question()

    async def _close_question(self) -> None:
        if self.state != QUESTION:
            return
        self._cancel_timer()
        self.state = REVEAL
        await self._to_hosts(self._reveal_for_host(self.index))
        for p in list(self.players.values()):
            await self._to_player(p, self._reveal_for_player(self.index, p))

    async def _finish(self) -> None:
        self._cancel_timer()
        self.state = FINISHED
        # Сначала пишем в базу: клиент сразу после game:finished может открыть отчёт.
        await self._persist()
        await self._to_hosts(self._final_for_host())
        for p in list(self.players.values()):
            await self._to_player(p, self._final_for_player(p))

    async def _kick(self, player_id: Any) -> None:
        if self.state != LOBBY:
            raise GameError("Удалять игроков можно только в лобби")
        p = self.players.pop(player_id, None) if isinstance(player_id, int) else None
        if p is None:
            raise GameError("Игрок не найден")
        for ws in list(p.sockets):
            await self._send(ws, {"type": "kicked"})
            try:
                await ws.close(code=4001)
            except Exception:
                pass
        async with SessionLocal() as db:
            await db.execute(delete(Player).where(Player.id == player_id))
            await db.commit()
        await self.broadcast_lobby()

    # ---------- база ----------

    async def _mark_started(self) -> None:
        async with SessionLocal() as db:
            gs = await db.get(GameSession, self.session_id)
            if gs is not None:
                gs.status = "running"
                gs.started_at = datetime.now(UTC)
                await db.commit()

    async def _persist(self) -> None:
        try:
            async with SessionLocal() as db:
                gs = await db.get(GameSession, self.session_id)
                if gs is None:
                    return
                gs.status = "finished"
                gs.finished_at = datetime.now(UTC)
                ranks = {r["id"]: r["rank"] for r in self.leaderboard()}
                rows = await db.scalars(select(Player).where(Player.session_id == self.session_id))
                for row in rows:
                    st = self.players.get(row.id)
                    if st is None:
                        continue
                    row.final_score = st.score
                    row.final_rank = ranks[row.id]
                    row.reconnects = st.reconnects
                    for idx, a in st.answers.items():
                        db.add(
                            PlayerAnswer(
                                player_id=row.id,
                                question_index=idx,
                                value=a["value"],
                                is_correct=a["correct"],
                                response_ms=a["ms"],
                                points=a["points"],
                            )
                        )
                await db.commit()
        except Exception:
            log.exception("Не удалось сохранить итоги игры %s", self.session_id)


class GameError(Exception):
    pass


def _shuffle_not_identity(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    shuffled = items[:]
    for _ in range(10):
        random.shuffle(shuffled)
        if [o["id"] for o in shuffled] != [o["id"] for o in items]:
            break
    return shuffled


class GameManager:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}

    def get(self, pin: str) -> Room | None:
        return self.rooms.get(pin)

    def new_pin(self) -> str:
        for _ in range(1000):
            pin = f"{random.randint(0, 999_999):06d}"
            room = self.rooms.get(pin)
            if room is None or room.state == FINISHED:
                return pin
        raise RuntimeError("Нет свободных PIN-кодов")

    def create(self, session_id: int, pin: str, host_id: int, title: str, questions: list[dict[str, Any]]) -> Room:
        room = Room(session_id, pin, host_id, title, questions)
        self.rooms[pin] = room
        return room


manager = GameManager()
