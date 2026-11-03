"""Ограничения аутентификации для единственного процесса API."""

import time
from collections import OrderedDict, deque

from fastapi import HTTPException, Request


class AuthRateLimit:
    def __init__(self) -> None:
        self.attempts: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()

    def check(self, request: Request, action: str) -> None:
        host = request.client.host if request.client else "unknown"
        key = (action, host)
        now = time.monotonic()
        entries = self.attempts.setdefault(key, deque())
        while entries and entries[0] <= now - 60:
            entries.popleft()
        self.attempts.move_to_end(key)
        while len(self.attempts) > 10_000:
            self.attempts.popitem(last=False)
        limit = 20 if action == "login" else 10
        if len(entries) >= limit:
            raise HTTPException(429, "Слишком много попыток. Подождите минуту", headers={"Retry-After": "60"})
        entries.append(now)
