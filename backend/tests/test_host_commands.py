"""R20 из аудита готовности от 5 ноября: запоздавшая команда ведущего не трогает следующий вопрос."""

import asyncio

from app.game.engine import QUESTION, REVEAL, Room

Q = {
    "id": 1,
    "type": "single",
    "text": "?",
    "time_limit": 20,
    "options": [{"id": 1, "text": "да"}, {"id": 2, "text": "нет"}],
    "correct_option_id": 1,
}


def test_stale_skip_does_not_close_next_question():
    async def scenario():
        room = Room(1, "000002", 1, "Т", [Q, {**Q, "id": 2}])
        room.add_player(1, "Аня", {}, "a")
        await room._start_question(0)
        await room.handle(None, None, {"type": "host:skip", "questionIndex": 0})
        assert room.state == REVEAL
        await room.handle(None, None, {"type": "host:next", "questionIndex": 0})
        assert room.state == QUESTION and room.index == 1
        await room.handle(None, None, {"type": "host:skip", "questionIndex": 0})  # запоздало
        await room.handle(None, None, {"type": "host:next", "questionIndex": 0})  # двойное нажатие
        state, index = room.state, room.index
        await room.handle(None, None, {"type": "host:skip"})  # старый клиент без номера
        after = room.state
        room._cancel_timer()
        return state, index, after

    assert asyncio.run(scenario()) == (QUESTION, 1, REVEAL)
