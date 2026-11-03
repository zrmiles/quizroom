import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from anyio import CapacityLimiter
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import update

from app.config import settings
from app.db import SessionLocal, engine, init_db
from app.game.engine import manager
from app.models import GameSession
from app.rate_limits import AuthRateLimit
from app.routers import auth, quizzes, sessions, ws

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    application.state.password_limiter = CapacityLimiter(4)
    application.state.auth_rate_limit = AuthRateLimit()
    await init_db()
    # Комнаты живут в памяти: после перезапуска незаконченные игры продолжить нельзя.
    async with SessionLocal() as db:
        await db.execute(
            update(GameSession).where(GameSession.status.in_(["lobby", "running"])).values(status="aborted")
        )
        await db.commit()
    sweeper = asyncio.create_task(_sweep_rooms())
    try:
        yield
    finally:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper
        for room in list(manager.rooms.values()):
            await room.shutdown("Сервер перезапускается")
        manager.rooms.clear()
        manager.reserved_pins.clear()
        await engine.dispose()


async def _sweep_rooms() -> None:
    """Раз в 5 минут убираем из памяти закончившиеся и брошенные комнаты."""
    while True:
        await asyncio.sleep(300)
        try:
            await manager.sweep()
        except Exception:
            logging.getLogger("quizroom").exception("Не удалось почистить комнаты")


app = FastAPI(title="QuizRoom API", version="0.1.0", lifespan=lifespan)

# Понятные тексты для частых ошибок проверки (остальные — как есть).
_ERROR_TEXT = {
    "finite_number": "Нужно обычное число",
    "float_parsing": "Нужно число",
    "int_parsing": "Нужно целое число",
    "less_than_equal": "Слишком большое значение",
    "greater_than_equal": "Слишком маленькое значение",
    "string_too_short": "Слишком коротко",
    "string_too_long": "Слишком длинно",
    "too_long": "Слишком много элементов",
    "missing": "Обязательное поле",
    "json_invalid": "Запрос не похож на JSON",
}


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Ответ 422 без введённых значений: в них может быть Infinity/NaN, а это ломает JSON-ответ (500)."""
    detail = [
        {
            "type": e.get("type"),
            "loc": list(e.get("loc", [])),
            "msg": _ERROR_TEXT.get(e.get("type", ""), e.get("msg", "Неверное значение")),
        }
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detail})


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(quizzes.router)
app.include_router(sessions.router)
app.include_router(ws.router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
