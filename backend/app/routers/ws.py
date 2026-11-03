import asyncio
import json
import math

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.game.engine import manager
from app.security import decode_access_token

router = APIRouter()

AUTH_TIMEOUT_S = 10


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


async def _reject(ws: WebSocket, message: str, code: int) -> None:
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
    if not isinstance(msg, dict) or msg.get("type") != "auth":
        return None
    role, token = msg.get("role"), msg.get("token")
    if role not in ("host", "player") or not isinstance(token, str) or not 1 <= len(token) <= 4096:
        return None
    return role, token


@router.websocket("/ws/game/{pin}")
async def game_socket(ws: WebSocket, pin: str, role: str = "player", token: str = "") -> None:
    """Одно соединение — ведущий (role=host, токен — JWT) или игрок (токен из /join).

    Токен передаётся первым сообщением `auth`. Параметры ?role=&token= в адресе
    поддерживаются для тестов и скриптов, но клиент ими не пользуется.
    """
    await ws.accept()
    if not token:
        auth = await _receive_auth(ws)
        if auth is None:
            await _reject(ws, "Не удалось войти в комнату", 4401)
            return
        role, token = auth

    room = manager.get(pin)
    if room is None:
        await _reject(ws, "Комната не найдена", 4404)
        return

    player = None
    if role == "host":
        if decode_access_token(token) != room.host_id:
            await _reject(ws, "Это не ваша игра", 4403)
            return
    else:
        player = room.player_by_token(token)
        if player is None:
            await _reject(ws, "Войдите в комнату заново", 4403)
            return

    async with room.lock:
        if manager.get(pin) is not room or (player is not None and player.id not in room.players):
            await _reject(ws, "Комната закрыта или игрок удалён", 4404)
            return
        room.attach(ws, player)
        await room._send(ws, room.snapshot(player))
        if player is not None:
            await room.broadcast_lobby()
    try:
        while True:
            raw = await ws.receive_text()
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
