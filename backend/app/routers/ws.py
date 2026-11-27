import asyncio
import json
import math
import time
from collections import Counter

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db import SessionLocal
from app.deps import user_from_token
from app.game.engine import manager

router = APIRouter()

AUTH_TIMEOUT_S = 10
# Один и тот же ответ на «нет комнаты», «чужой токен» и «нет авторизации»: по различию
# можно было бы перебором находить идущие игры, не упираясь в лимит неверных PIN.
DENIED_TEXT = "Не удалось войти в комнату. Проверьте код или войдите заново"
DENIED_CODE = 4403
# Соединения с одного адреса, ещё не прошедшие авторизацию. Класс за одним роутером
# подключается почти одновременно, поэтому запас большой; поток пустых соединений — нет.
MAX_PENDING_PER_ADDRESS = 100
# Сообщений в секунду с одного соединения. Человек нажимает кнопки гораздо реже.
MAX_MESSAGES_PER_S = 20
FLOOD_CODE = 4429

_pending: Counter[str] = Counter()


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Неконечное число")
    return result


def _invalid_constant(_: str) -> None:
    raise ValueError("Неконечное число")


def parse_message(raw: str) -> dict:
    if len(raw) > 65536:
        raise ValueError("Слишком большое сообщение")
    msg = json.loads(raw, parse_constant=_invalid_constant, parse_float=_finite_float)
    if not isinstance(msg, dict):
        raise ValueError("Нужен объект")
    return msg


async def _reject(ws: WebSocket, message: str = DENIED_TEXT, code: int = DENIED_CODE) -> None:
    try:
        await ws.send_json({"type": "error", "message": message})
        await ws.close(code=code)
    except Exception:  # клиент уже ушёл
        pass


async def _receive_auth(ws: WebSocket) -> tuple[str, str] | None:
    """Первое сообщение клиента: {"type": "auth", "role": "host"|"player", "token": "..."}.

    Токен не кладём в адрес соединения — иначе он оседает в логах uvicorn и nginx.
    """
    try:
        raw = await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT_S)
        msg = parse_message(raw)
    except (TimeoutError, WebSocketDisconnect, ValueError, KeyError, RuntimeError, RecursionError):
        return None
    if msg.get("type") != "auth":
        return None
    role, token = msg.get("role"), msg.get("token")
    if role not in ("host", "player") or not isinstance(token, str) or not 1 <= len(token) <= 4096:
        return None
    return role, token


@router.websocket("/ws/game/{pin}")
async def game_socket(ws: WebSocket, pin: str) -> None:
    """Одно соединение — ведущий (токен — JWT) или игрок (токен из /join). Токен — первым сообщением `auth`."""
    address = ws.client.host if ws.client else "unknown"
    if _pending[address] >= MAX_PENDING_PER_ADDRESS:
        await ws.close(code=FLOOD_CODE)
        return
    _pending[address] += 1
    try:
        await ws.accept()
        auth = await _receive_auth(ws)
    finally:
        _pending[address] -= 1
        if _pending[address] <= 0:
            del _pending[address]
    if auth is None:
        await _reject(ws)
        return
    role, token = auth

    room = manager.get(pin)
    player = None
    if room is None:
        await _reject(ws)
        return
    if role == "host":
        # Через базу, а не только подпись: токен, отозванный сменой пароля, не пускает в комнату.
        async with SessionLocal() as db:
            user = await user_from_token(db, token)
        if user is None or user.id != room.host_id:
            await _reject(ws)
            return
    else:
        player = room.player_by_token(token)
        if player is None:
            await _reject(ws)
            return

    async with room.lock:
        if manager.get(pin) is not room or (player is not None and player.id not in room.players):
            await _reject(ws, "Комната закрыта или вас удалили из неё", 4404)
            return
        room.attach(ws, player)
        await room._send(ws, room.snapshot(player))
        if player is not None:
            await room.broadcast_lobby()
    window_start, in_window = time.monotonic(), 0
    try:
        while True:
            raw = await ws.receive_text()
            now = time.monotonic()
            if now - window_start >= 1:
                window_start, in_window = now, 0
            in_window += 1
            if in_window > MAX_MESSAGES_PER_S:
                await _reject(ws, "Слишком много сообщений. Переподключаемся", FLOOD_CODE)
                break
            try:
                msg = parse_message(raw)
            except (ValueError, RecursionError):
                await room._send(ws, {"type": "error", "message": "Непонятное сообщение"})
                continue
            await room.handle(ws, player, msg)
    except (WebSocketDisconnect, RuntimeError, KeyError):
        pass
    finally:
        room.detach(ws, player)
        if player is not None and player.id in room.players:
            await room.broadcast_lobby()
            await room.after_disconnect()
