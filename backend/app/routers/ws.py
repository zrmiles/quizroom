from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.game.engine import manager
from app.security import decode_access_token

router = APIRouter()


@router.websocket("/ws/game/{pin}")
async def game_socket(ws: WebSocket, pin: str, role: str = "player", token: str = "") -> None:
    """Одно соединение — ведущий (role=host, token=JWT) или игрок (token из /join)."""
    await ws.accept()
    room = manager.get(pin)
    if room is None:
        await ws.send_json({"type": "error", "message": "Комната не найдена"})
        await ws.close(code=4404)
        return

    player = None
    if role == "host":
        if decode_access_token(token) != room.host_id:
            await ws.send_json({"type": "error", "message": "Это не ваша игра"})
            await ws.close(code=4403)
            return
    else:
        player = room.player_by_token(token)
        if player is None:
            await ws.send_json({"type": "error", "message": "Войдите в комнату заново"})
            await ws.close(code=4403)
            return

    room.attach(ws, player)
    await ws.send_json(room.snapshot(player))
    if player is not None:
        await room.broadcast_lobby()
    try:
        while True:
            msg = await ws.receive_json()
            await room.handle(ws, player, msg)
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        room.detach(ws, player)
        if player is not None and player.id in room.players:
            await room.broadcast_lobby()
            await room.after_disconnect()
