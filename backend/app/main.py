import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import GameSession
from app.routers import auth, quizzes, sessions, ws

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await init_db()
    # Комнаты живут в памяти: после перезапуска незаконченные игры продолжить нельзя.
    async with SessionLocal() as db:
        await db.execute(
            update(GameSession).where(GameSession.status.in_(["lobby", "running"])).values(status="aborted")
        )
        await db.commit()
    yield


app = FastAPI(title="QuizRoom API", version="0.1.0", lifespan=lifespan)
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
