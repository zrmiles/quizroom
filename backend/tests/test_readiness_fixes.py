"""Регрессии на находки аудита готовности от 5 ноября (R04, R05, R07, R11, R22, R23)."""

import asyncio
from unittest.mock import patch

from app.game import engine
from app.game.engine import QUESTION, REVEAL, Room

SINGLE = {
    "id": 1,
    "type": "single",
    "text": "?",
    "time_limit": 20,
    "options": [{"id": 1, "text": "да"}, {"id": 2, "text": "нет"}],
    "correct_option_id": 1,
}
ANSWER = {"type": "player:answer", "questionIndex": 0, "value": {"option_id": 1}}


class FakeSocket:
    async def send_json(self, _msg):
        pass

    async def close(self, code=1000):
        pass


async def _two_players_on_question():
    room = Room(1, "000001", 1, "Т", [SINGLE])
    a = room.add_player(1, "Аня", {}, "a")
    b = room.add_player(2, "Борис", {}, "b")
    sa, sb = FakeSocket(), FakeSocket()
    room.attach(sa, a)
    room.attach(sb, b)
    await room._start_question(0)
    return room, a, b, sa, sb


async def _cleanup(room):
    room._cancel_timer()
    for task in list(room.rechecks) + list(room.senders.values()):
        task.cancel()
    await asyncio.sleep(0)


# ---------- R04: короткий обрыв связи не стоит ответа ----------


def test_short_disconnect_keeps_question_open():
    async def scenario():
        room, a, b, _, sb = await _two_players_on_question()
        await room.handle(None, a, ANSWER)
        room.detach(sb, b)
        await room.after_disconnect()
        assert room.state == QUESTION  # Бориса ещё ждём
        room.attach(FakeSocket(), b)
        await room.handle(None, b, ANSWER)
        state = room.state
        await _cleanup(room)
        return state, b.answers

    state, answers = asyncio.run(scenario())
    assert state == REVEAL
    assert answers[0]["correct"] is True


def test_player_gone_for_good_does_not_hold_the_room():
    async def scenario():
        with patch.object(engine, "RECONNECT_GRACE_MS", 50):
            room, a, b, _, sb = await _two_players_on_question()
            await room.handle(None, a, ANSWER)
            room.detach(sb, b)
            await room.after_disconnect()
            assert room.state == QUESTION
            await asyncio.sleep(0.15)
            state = room.state
            await _cleanup(room)
            return state

    assert asyncio.run(scenario()) == REVEAL


def test_question_waits_for_timer_when_everyone_dropped():
    async def scenario():
        with patch.object(engine, "RECONNECT_GRACE_MS", 50):
            room, a, b, sa, sb = await _two_players_on_question()
            room.detach(sa, a)
            room.detach(sb, b)
            await room.after_disconnect()
            await asyncio.sleep(0.15)
            state = room.state
            await _cleanup(room)
            return state

    assert asyncio.run(scenario()) == QUESTION
