import asyncio
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.game.engine import manager
from app.models import AnswerOption, Question, Quiz, User
from app.schemas import DbIdPath, QuizIn, QuizOut, QuizSummary

router = APIRouter(prefix="/api/quizzes", tags=["quizzes"])

_with_questions = selectinload(Quiz.questions).selectinload(Question.options)

# Проверка версии и запись идут под одной блокировкой на викторину: API работает одним процессом,
# а SQLite не блокирует строку при чтении, поэтому без неё два PUT могли бы пройти проверку оба.
_edit_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def load_quiz(db: AsyncSession, quiz_id: int, user: User) -> Quiz:
    quiz = await db.scalar(
        select(Quiz).where(Quiz.id == quiz_id).options(_with_questions).execution_options(populate_existing=True)
    )
    if quiz is None or (quiz.owner_id != user.id and not quiz.is_public):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Викторина не найдена")
    return quiz


def _own(quiz: Quiz, user: User) -> None:
    if quiz.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Это не ваша викторина")


def _fill(quiz: Quiz, data: QuizIn) -> None:
    quiz.title = data.title.strip()
    quiz.description = data.description.strip()
    quiz.is_public = data.is_public
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
    quizzes = await db.scalars(
        select(Quiz)
        .where(Quiz.owner_id == user.id)
        .options(selectinload(Quiz.questions))
        .order_by(Quiz.updated_at.desc())
    )
    return [
        QuizSummary(id=q.id, title=q.title, question_count=len(q.questions), updated_at=q.updated_at) for q in quizzes
    ]


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
    async with _edit_locks[quiz_id]:
        quiz = await load_quiz(db, quiz_id, user)
        _own(quiz, user)
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
    owner_id = await db.scalar(select(Quiz.owner_id).where(Quiz.id == quiz_id))
    if owner_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Викторина не найдена")
    if owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Это не ваша викторина")
    # Сначала закрываем идущие комнаты этой викторины, чтобы игроки не упирались в удалённую сессию.
    await manager.close_quiz_rooms(quiz_id)
    # Вопросы, варианты, сессии и ответы удаляет база по ON DELETE CASCADE.
    await db.execute(delete(Quiz).where(Quiz.id == quiz_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
