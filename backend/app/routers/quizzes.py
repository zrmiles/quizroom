import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.game.engine import manager
from app.models import AnswerOption, Question, Quiz, User
from app.schemas import DbIdPath, QuizIn, QuizOut, QuizSummary

router = APIRouter(prefix="/api/quizzes", tags=["quizzes"])

_with_questions = selectinload(Quiz.questions).selectinload(Question.options)


class KeyedLocks:
    """Блокировка на ключ, которая исчезает, когда её никто не ждёт: словарь не растёт без конца."""

    def __init__(self) -> None:
        self._locks: dict[int, tuple[asyncio.Lock, int]] = {}

    def __len__(self) -> int:
        return len(self._locks)

    @asynccontextmanager
    async def hold(self, key: int) -> AsyncIterator[None]:
        lock, users = self._locks.get(key, (asyncio.Lock(), 0))
        self._locks[key] = (lock, users + 1)
        try:
            async with lock:
                yield
        finally:
            lock, users = self._locks[key]
            if users == 1:
                del self._locks[key]
            else:
                self._locks[key] = (lock, users - 1)


# Проверка версии и запись идут под одной блокировкой на викторину: API работает одним процессом,
# а SQLite не блокирует строку при чтении, поэтому без неё два PUT могли бы пройти проверку оба.
_edit_locks = KeyedLocks()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def load_quiz(db: AsyncSession, quiz_id: int, user: User) -> Quiz:
    quiz = await db.scalar(
        select(Quiz).where(Quiz.id == quiz_id).options(_with_questions).execution_options(populate_existing=True)
    )
    # Только свои: чужие викторины содержат правильные ответы, поэтому открывать их нельзя никому.
    if quiz is None or quiz.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Викторина не найдена")
    return quiz


async def _owned_id(db: AsyncSession, quiz_id: int, user: User) -> None:
    """Своя ли это викторина. Чужая отвечает так же, как несуществующая: ID не раскрывается."""
    owner_id = await db.scalar(select(Quiz.owner_id).where(Quiz.id == quiz_id))
    if owner_id is None or owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Викторина не найдена")


def _fill(quiz: Quiz, data: QuizIn) -> None:
    quiz.title = data.title.strip()
    quiz.description = data.description.strip()
    # Доступ для других ведущих убран: так они видели правильные ответы. Поле оставлено для совместимости.
    quiz.is_public = False
    # Явное время с микросекундами: правка только вопросов тоже меняет дату, и две быстрые
    # правки подряд получают разные версии (у SQLite CURRENT_TIMESTAMP — с точностью до секунды).
    quiz.updated_at = datetime.now(UTC)
    quiz.questions.clear()
    for pos, q in enumerate(data.questions):
        question = Question(
            position=pos,
            type=q.type,
            text=q.text,
            time_limit=q.time_limit,
            number_answer=q.number_answer,
            number_min=q.number_min,
            number_max=q.number_max,
            number_tolerance=q.number_tolerance,
            number_exact_bonus=q.number_exact_bonus,
            options=[AnswerOption(position=i, text=o.text, is_correct=o.is_correct) for i, o in enumerate(q.options)],
        )
        quiz.questions.append(question)


@router.get("", response_model=list[QuizSummary])
async def list_my_quizzes(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Число вопросов считает база — сами вопросы для списка не нужны.
    counts = select(Question.quiz_id, func.count(Question.id).label("n")).group_by(Question.quiz_id).subquery()
    rows = await db.execute(
        select(Quiz.id, Quiz.title, Quiz.updated_at, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.quiz_id == Quiz.id)
        .where(Quiz.owner_id == user.id)
        .order_by(Quiz.updated_at.desc(), Quiz.id.desc())
    )
    return [QuizSummary(id=i, title=t, question_count=n, updated_at=u) for i, t, u, n in rows.all()]


@router.post("", response_model=QuizOut, status_code=status.HTTP_201_CREATED)
async def create_quiz(data: QuizIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    quiz = Quiz(owner_id=user.id, questions=[])
    _fill(quiz, data)
    db.add(quiz)
    await db.commit()
    return await load_quiz(db, quiz.id, user)


@router.get("/{quiz_id}", response_model=QuizOut)
async def get_quiz(quiz_id: DbIdPath, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await load_quiz(db, quiz_id, user)


@router.put("/{quiz_id}", response_model=QuizOut)
async def update_quiz(
    quiz_id: DbIdPath, data: QuizIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    # Сначала права: блокировка заводится только для своей существующей викторины.
    await _owned_id(db, quiz_id, user)
    async with _edit_locks.hold(quiz_id):
        quiz = await load_quiz(db, quiz_id, user)
        if data.base_updated_at is not None and _as_utc(data.base_updated_at) != _as_utc(quiz.updated_at):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Викторину уже изменили в другой вкладке или на другом устройстве",
            )
        _fill(quiz, data)
        await db.commit()
    return await load_quiz(db, quiz_id, user)


@router.delete("/{quiz_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quiz(quiz_id: DbIdPath, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _owned_id(db, quiz_id, user)
    # Сначала закрываем идущие комнаты этой викторины (сыгранное в них сохраняется как прерванная игра).
    await manager.close_quiz_rooms(quiz_id)
    # Вопросы и варианты удаляет база по ON DELETE CASCADE; проведённые игры и отчёты остаются.
    await db.execute(delete(Quiz).where(Quiz.id == quiz_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
