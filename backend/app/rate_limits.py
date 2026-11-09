"""Ограничения частоты запросов с одного адреса для единственного процесса API.

Лимиты рассчитаны на класс за одним NAT: 30 телефонов входят в игру почти одновременно,
а подбор PIN и заполнение комнаты фальшивыми игроками заметно замедляются.
"""

import time
from collections import OrderedDict, deque

from fastapi import HTTPException, Request

WINDOW_S = 60
LIMITS = {
    "login": 20,
    "register": 10,
    # Неверные PIN: обычный человек не ошибается 30 раз в минуту, а перебор кодов упирается в лимит.
    "pin_miss": 30,
    # Входы в комнаты с одного адреса: хватает на целый класс, но не на мгновенное заполнение комнаты.
    "join": 120,
}
MESSAGES = {
    "pin_miss": "Слишком много неверных кодов. Подождите минуту",
    "join": "Слишком много входов с этого адреса. Подождите минуту",
}


class RequestRateLimit:
    def __init__(self) -> None:
        self.attempts: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()

    def _entries(self, request: Request, action: str) -> deque[float]:
        host = request.client.host if request.client else "unknown"
        key = (action, host)
        now = time.monotonic()
        entries = self.attempts.setdefault(key, deque())
        while entries and entries[0] <= now - WINDOW_S:
            entries.popleft()
        self.attempts.move_to_end(key)
        while len(self.attempts) > 10_000:
            self.attempts.popitem(last=False)
        return entries

    def ensure_allowed(self, request: Request, action: str) -> None:
        """Отказать, если лимит уже исчерпан; саму попытку не считать."""
        if len(self._entries(request, action)) >= LIMITS[action]:
            message = MESSAGES.get(action, "Слишком много попыток. Подождите минуту")
            raise HTTPException(429, message, headers={"Retry-After": str(WINDOW_S)})

    def record(self, request: Request, action: str) -> None:
        self._entries(request, action).append(time.monotonic())

    def check(self, request: Request, action: str) -> None:
        """Проверить лимит и сразу засчитать попытку."""
        self.ensure_allowed(request, action)
        self.record(request, action)
