"""Игровой движок: комнаты в памяти процесса.

Сервер — единственный источник истины: он хранит состояние комнаты, сам закрывает
вопрос по таймеру и считает очки. Клиент лишь рисует таймер от `endsAt`.

Ограничение MVP: состояние живёт в памяти одного процесса API (один воркер uvicorn).
Для нескольких воркеров состояние переезжает в Redis — см. docs/PLAN.md.
"""

import asyncio
import logging
import random
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.config import settings
from app.db import SessionLocal
from app.game.scoring import is_exact, score
from app.models import GameSession, Player, PlayerAnswer
from app.schemas import GAME_COMMAND

log = logging.getLogger("quizroom.game")

LOBBY, QUESTION, REVEAL, FINISHED = "lobby", "question", "reveal", "finished"

SEND_TIMEOUT_S = 2.0  # зависший телефон не должен тормозить рассылку всей комнате
OUTBOX_LIMIT = 256
WAVE_COOLDOWN_MS = 1000  # «Помахать» — не чаще раза в секунду
FINISHED_ROOM_TTL_S = 30 * 60  # закончившуюся комнату держим полчаса (переподключиться к итогам)
IDLE_ROOM_TTL_S = 3 * 60 * 60  # брошенную комнату закрываем через 3 часа без действий


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
    # Переподключения во время игры (в лобби — не считаем: это не проблема связи).
    reconnects: int = 0
    last_wave_ms: int = 0
    sockets: set[WebSocket] = field(default_factory=set)
    answers: dict[int, dict[str, Any]] = field(default_factory=dict)

    @property
    def connected(self) -> bool:
        return bool(self.sockets)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nickname": self.nickname,
            "avatar": self.avatar,
            "connected": self.connected,
            "score": self.score,
        }


class Room:
    def __init__(
        self,
        session_id: int,
        pin: str,
        host_id: int,
        title: str,
        questions: list[dict[str, Any]],
        quiz_id: int | None = None,
    ):
        self.session_id = session_id
        self.quiz_id = quiz_id
        self.last_activity = time.monotonic()
        # Имена, которые сейчас регистрируются через /join (защита от одновременных входов).
        self.reserved_nicks: set[str] = set()
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
        self.outboxes: dict[WebSocket, asyncio.Queue[dict[str, Any] | int]] = {}
        self.senders: dict[WebSocket, asyncio.Task[None]] = {}
        self.closers: set[asyncio.Task[None]] = set()
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
        return low in self.reserved_nicks or any(p.nickname.casefold() == low for p in self.players.values())

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def player_by_token(self, token: str) -> PlayerState | None:
        return next((p for p in self.players.values() if p.token == token), None)

    def attach(self, ws: WebSocket, player: PlayerState | None) -> None:
        if player is None:
            self.host_sockets.add(ws)
        else:
            if player.connections > 0 and self.state in (QUESTION, REVEAL):
                player.reconnects += 1
            player.sockets.add(ws)
            player.connections += 1
        self._outbox(ws, player)
        self.touch()

    def detach(self, ws: WebSocket, player: PlayerState | None) -> None:
        if player is None:
            self.host_sockets.discard(ws)
        else:
            player.sockets.discard(ws)
        self.outboxes.pop(ws, None)
        task = self.senders.pop(ws, None)
        if task and task is not asyncio.current_task():
            task.cancel()

    def _outbox(self, ws: WebSocket, player: PlayerState | None) -> asyncio.Queue[dict[str, Any] | int]:
        queue = self.outboxes.get(ws)
        if queue is None:
            queue = asyncio.Queue(maxsize=OUTBOX_LIMIT)
            self.outboxes[ws] = queue
            self.senders[ws] = asyncio.create_task(self._drain(ws, player, queue))
        return queue

    async def _drain(
        self, ws: WebSocket, player: PlayerState | None, queue: asyncio.Queue[dict[str, Any] | int]
    ) -> None:
        """Одна очередь на соединение сохраняет порядок без сетевых ожиданий под lock комнаты."""
        try:
            while True:
                item = await queue.get()
                if isinstance(item, int):
                    await asyncio.wait_for(ws.close(code=item), SEND_TIMEOUT_S)
                    return
                await asyncio.wait_for(ws.send_json(item), SEND_TIMEOUT_S)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("Отключено медленное или закрытое соединение в %s", self.pin)
        finally:
            attached = ws in self.outboxes
            self.detach(ws, player)
            if attached:
                try:
                    await asyncio.wait_for(ws.close(code=1013), SEND_TIMEOUT_S)
                except Exception:
                    pass
                if player is not None and player.id in self.players:
                    await self.broadcast_lobby()
                    await self.after_disconnect()

    async def _send(self, ws: WebSocket, msg: dict[str, Any]) -> None:
        queue = self.outboxes.get(ws)
        if queue is None:
            return
        try:
            queue.put_nowait(msg)
        except asyncio.QueueFull:
            # Не держим неограниченную очередь для клиента, который не читает сообщения.
            self._drop_socket(ws)

    def _drop_socket(self, ws: WebSocket) -> None:
        player = next((p for p in self.players.values() if ws in p.sockets), None)
        self.detach(ws, player)

        async def close() -> None:
            try:
                await asyncio.wait_for(ws.close(code=1013), SEND_TIMEOUT_S)
            except Exception:
                pass

        task = asyncio.create_task(close())
        self.closers.add(task)
        task.add_done_callback(self.closers.discard)

    async def _close_socket(self, ws: WebSocket, code: int) -> None:
        queue = self.outboxes.get(ws)
        if queue is not None:
            try:
                queue.put_nowait(code)
            except asyncio.QueueFull:
                self._drop_socket(ws)

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
        """Равные очки — общее место (1, 2, 2, 4), как в спорте."""
        ranked = sorted(self.players.values(), key=lambda p: (-p.score, p.nickname.casefold()))
        board = []
        for i, p in enumerate(ranked):
            rank = board[-1]["rank"] if board and board[-1]["score"] == p.score else i + 1
            board.append({**p.public(), "rank": rank})
        return board

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
                "value": a["value"] if a else None,
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
                snap["yourAnswer"] = player.answers.get(self.index, {}).get("value")
        elif self.state == REVEAL:
            snap["reveal"] = (
                self._reveal_for_host(self.index) if player is None else self._reveal_for_player(self.index, player)
            )
        elif self.state == FINISHED:
            snap["final"] = self._final_for_host() if player is None else self._final_for_player(player)
        return snap

    # ---------- команды ----------

    async def handle(self, ws: WebSocket, player: PlayerState | None, msg: dict[str, Any]) -> None:
        # Время получения фиксируем до ожидания lock: задержка сервера (запись в базу,
        # очередь команд) не должна превращать своевременный ответ в просроченный.
        received_ms = now_ms()
        try:
            msg = GAME_COMMAND.validate_python(msg).model_dump()
        except ValidationError:
            await self._send(ws, {"type": "error", "message": "Неверный формат команды"})
            return
        kind = msg["type"]
        async with self.lock:
            self.touch()
            try:
                if player is None:
                    await self._handle_host(kind, msg)
                elif player.id in self.players:  # удалённый игрок команд не шлёт
                    await self._handle_player(player, kind, msg, received_ms)
            except GameError as e:
                await self._send(ws, {"type": "error", "message": str(e)})
            except Exception:
                log.exception("Ошибка в комнате %s при команде %s", self.pin, kind)
                await self._send(ws, {"type": "error", "message": "Что-то пошло не так на сервере. Попробуйте ещё раз"})

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

    async def _handle_player(self, p: PlayerState, kind: Any, msg: dict[str, Any], received_ms: int) -> None:
        if kind == "player:answer":
            await self._submit(p, msg.get("questionIndex"), msg.get("value"), received_ms)
        elif kind == "player:wave":
            now = now_ms()
            if now - p.last_wave_ms < WAVE_COOLDOWN_MS:
                return  # без ошибки: просто не рассылаем слишком частые «помахать»
            p.last_wave_ms = now
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

    async def _submit(self, p: PlayerState, question_index: Any, value: Any, received_ms: int | None = None) -> None:
        if self.state != QUESTION or question_index != self.index:
            raise GameError("Вопрос уже закрыт")
        now = received_ms if received_ms is not None else now_ms()
        if now > self.ends_at_ms + settings.answer_grace_ms:
            raise GameError("Время вышло")
        if self.index in p.answers:
            await self._ack(p)
            return
        q = self.questions[self.index]
        response_ms = max(0, now - self.started_at_ms)
        try:
            correct, points = score(q, value, response_ms)
        except (ValueError, KeyError, TypeError) as e:
            raise GameError(str(e) or "Неверный ответ") from e
        exact = q["type"] == "number" and is_exact(float(value["number"]), q["answer"], q["tolerance"])
        p.answers[self.index] = {
            "value": value,
            "correct": correct,
            "points": points,
            "ms": response_ms,
            "exact": exact,
        }
        p.score += points
        await self._ack(p)
        answered = sum(1 for pl in self.players.values() if self.index in pl.answers)
        await self._to_hosts({"type": "question:progress", "answered": answered, "total": len(self.players)})
        waiting = [pl for pl in self.players.values() if pl.connected and self.index not in pl.answers]
        if not waiting:
            await self._close_question()

    async def _ack(self, p: PlayerState) -> None:
        await self._to_player(
            p, {"type": "answer:ack", "questionIndex": self.index, "value": p.answers[self.index]["value"]}
        )

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
        if self.state == QUESTION:
            await self._close_question()
        else:
            self._cancel_timer()
        # Ошибка оставляет комнату на разборе: ведущий может повторить завершение.
        await self._persist()
        self.state = FINISHED
        await self._to_hosts(self._final_for_host())
        for p in list(self.players.values()):
            await self._to_player(p, self._final_for_player(p))

    async def _kick(self, player_id: Any) -> None:
        if self.state != LOBBY:
            raise GameError("Удалять игроков можно только в лобби")
        p = self.players.get(player_id) if isinstance(player_id, int) else None
        if p is None:
            raise GameError("Игрок не найден")
        # Сначала база, потом память: при сбое база и комната остаются согласованными,
        # а ведущий может повторить удаление.
        try:
            async with SessionLocal() as db:
                await db.execute(delete(Player).where(Player.id == player_id))
                await db.commit()
        except Exception as e:
            log.exception("Не удалось удалить игрока %s из базы", player_id)
            raise GameError("Не удалось удалить игрока. Попробуйте ещё раз") from e
        self.players.pop(player_id, None)
        for ws in list(p.sockets):
            await self._send(ws, {"type": "kicked"})
            await self._close_socket(ws, 4001)
        await self.broadcast_lobby()

    async def shutdown(self, reason: str) -> None:
        """Закрыть комнату для всех: викторину удалили или комната брошена."""
        self._cancel_timer()
        self.state = FINISHED
        sockets = list(self.outboxes)
        tasks = list(self.senders.values())
        for ws in sockets:
            player = next((p for p in self.players.values() if ws in p.sockets), None)
            self.detach(ws, player)
        await asyncio.gather(*tasks, return_exceptions=True)

        async def close(ws: WebSocket) -> None:
            try:
                await asyncio.wait_for(ws.send_json({"type": "error", "message": reason}), SEND_TIMEOUT_S)
            except Exception:
                pass
            try:
                await asyncio.wait_for(ws.close(code=4404), SEND_TIMEOUT_S)
            except Exception:
                pass

        await asyncio.gather(*(close(ws) for ws in sockets))
        await asyncio.gather(*list(self.closers), return_exceptions=True)

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
                    raise GameError("Игра удалена, сохранить итоги нельзя")
                gs.status = "finished"
                if gs.finished_at is None:  # повтор сохранения не переписывает историю
                    gs.finished_at = datetime.now(UTC)
                ranks = {r["id"]: r["rank"] for r in self.leaderboard()}
                # Строки игроков без состояния в комнате (неудачный вход или удаление) в итоги не попадают.
                await db.execute(
                    delete(Player).where(Player.session_id == self.session_id, Player.id.not_in(list(self.players)))
                )
                rows = await db.scalars(select(Player).where(Player.session_id == self.session_id))
                # Повтор после неопределённого исхода commit безопасен: запись целиком атомарна.
                await db.execute(
                    delete(PlayerAnswer).where(
                        PlayerAnswer.player_id.in_(select(Player.id).where(Player.session_id == self.session_id))
                    )
                )
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
        except GameError:
            raise
        except Exception as e:
            log.exception("Не удалось сохранить итоги игры %s", self.session_id)
            raise GameError("Не удалось сохранить итоги. Попробуйте завершить игру ещё раз") from e


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
        self.reserved_pins: set[str] = set()

    def get(self, pin: str) -> Room | None:
        return self.rooms.get(pin)

    def new_pin(self) -> str:
        for _ in range(1000):
            pin = f"{secrets.randbelow(1_000_000):06d}"
            if pin not in self.rooms and pin not in self.reserved_pins:
                return pin
        raise RuntimeError("Нет свободных PIN-кодов")

    def reserve_pin(self) -> str:
        pin = self.new_pin()
        self.reserved_pins.add(pin)
        return pin

    def create(
        self,
        session_id: int,
        pin: str,
        host_id: int,
        title: str,
        questions: list[dict[str, Any]],
        quiz_id: int | None = None,
    ) -> Room:
        if pin in self.rooms:
            raise RuntimeError("PIN уже занят")
        room = Room(session_id, pin, host_id, title, questions, quiz_id=quiz_id)
        self.rooms[pin] = room
        self.reserved_pins.discard(pin)
        return room

    async def close_quiz_rooms(self, quiz_id: int) -> None:
        for pin, room in list(self.rooms.items()):
            if room.quiz_id == quiz_id:
                async with room.lock:
                    await room.shutdown("Ведущий удалил эту викторину")
                self.rooms.pop(pin, None)

    async def sweep(self) -> None:
        """Убрать из памяти закончившиеся и брошенные комнаты."""
        now = time.monotonic()
        for pin, room in list(self.rooms.items()):
            idle = now - room.last_activity
            if room.state == FINISHED and idle > FINISHED_ROOM_TTL_S:
                async with room.lock:
                    if time.monotonic() - room.last_activity <= FINISHED_ROOM_TTL_S:
                        continue
                    await room.shutdown("Время хранения итогов комнаты истекло")
                self.rooms.pop(pin, None)
            elif room.state != FINISHED and idle > IDLE_ROOM_TTL_S:
                async with room.lock:
                    if time.monotonic() - room.last_activity <= IDLE_ROOM_TTL_S:
                        continue
                    await room.shutdown("Комната закрыта: давно не было активности")
                await _mark_aborted(room.session_id)
                self.rooms.pop(pin, None)


async def _mark_aborted(session_id: int) -> None:
    try:
        async with SessionLocal() as db:
            gs = await db.get(GameSession, session_id)
            if gs is not None and gs.status != "finished":
                gs.status = "aborted"
                await db.commit()
    except Exception:
        log.exception("Не удалось пометить игру %s прерванной", session_id)


manager = GameManager()
