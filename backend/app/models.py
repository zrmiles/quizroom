from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(40))
    password_hash: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    questions: Mapped[list["Question"]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan", order_by="Question.position"
    )
    sessions: Mapped[list["GameSession"]] = relationship(back_populates="quiz", cascade="all, delete-orphan")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(10))  # single | number | order
    text: Mapped[str] = mapped_column(Text)
    time_limit: Mapped[int] = mapped_column(Integer, default=20)
    # Только для type=number
    number_answer: Mapped[float | None] = mapped_column(Float, nullable=True)
    number_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    number_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    number_tolerance: Mapped[float | None] = mapped_column(Float, nullable=True)
    number_exact_bonus: Mapped[bool] = mapped_column(Boolean, default=False)

    quiz: Mapped[Quiz] = relationship(back_populates="questions")
    options: Mapped[list["AnswerOption"]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="AnswerOption.position"
    )


class AnswerOption(Base):
    """Вариант ответа. Для type=order позиция = правильный порядок."""

    __tablename__ = "answer_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(String(200))
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)

    question: Mapped[Question] = relationship(back_populates="options")


class GameSession(Base):
    """Одна проведённая игра. Вопросы копируются в snapshot при запуске,
    поэтому правка викторины потом не ломает историю и отчёты."""

    __tablename__ = "game_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    pin: Mapped[str] = mapped_column(String(6), index=True)
    title: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(12), default="lobby")  # lobby | running | finished
    snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    parent_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    quiz: Mapped[Quiz] = relationship(back_populates="sessions")
    players: Mapped[list["Player"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    nickname: Mapped[str] = mapped_column(String(16))
    avatar: Mapped[dict[str, Any]] = mapped_column(JSON)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    final_score: Mapped[int] = mapped_column(Integer, default=0)
    final_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reconnects: Mapped[int] = mapped_column(Integer, default=0)

    session: Mapped[GameSession] = relationship(back_populates="players")
    answers: Mapped[list["PlayerAnswer"]] = relationship(back_populates="player", cascade="all, delete-orphan")


class PlayerAnswer(Base):
    __tablename__ = "player_answers"
    __table_args__ = (UniqueConstraint("player_id", "question_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    question_index: Mapped[int] = mapped_column(Integer)  # индекс в GameSession.snapshot
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    response_ms: Mapped[int] = mapped_column(Integer)
    points: Mapped[int] = mapped_column(Integer)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    player: Mapped[Player] = relationship(back_populates="answers")
