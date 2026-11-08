import secrets
from copy import deepcopy
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.game.engine import FINISHED, manager
from app.models import GameSession, Player, Question, Quiz, User
from app.routers.quizzes import load_quiz
from app.schemas import (
    DbIdPath,
    JoinIn,
    JoinOut,
    SessionCreatedOut,
    SessionCreateIn,
    SessionHistoryItem,
    SessionPublicOut,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

# Вопрос «трудный», если верно ответили меньше половины тех, кто мог ответить.
# Это же правило решает, что попадёт в «повторить только ошибки».
HARD_RATE = 0.5
# Служебные отметки отчёта в снимке, которые не переносятся в новую игру.
PLAY_MARKS = ("eligible", "shown")


def build_snapshot(questions: list[Question]) -> list[dict[str, Any]]:
    """Копия вопросов на момент запуска игры — вместе с правильными ответами."""
    snap = []
    for q in questions:
        options = [{"id": o.id, "text": o.text} for o in q.options]
        item: dict[str, Any] = {
            "id": q.id,
            "type": q.type,
            "text": q.text,
            "time_limit": q.time_limit,
            "options": options,
        }
        if q.type == "single":
            item["correct_option_id"] = next(o.id for o in q.options if o.is_correct)
        elif q.type == "number":
            item.update(
                answer=q.number_answer,
                min=q.number_min,
                max=q.number_max,
                tolerance=q.number_tolerance,
                exact_bonus=q.number_exact_bonus,
            )
        elif q.type == "order":
            item["correct_order"] = [o["id"] for o in options]
        snap.append(item)
    return snap


def _session_snapshot(snapshot: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Новые непрозрачные ID также при повторе игр, созданных до исправления."""
    snapshot = deepcopy(snapshot)
    for q in snapshot:
        for key in PLAY_MARKS:
            q.pop(key, None)
        if q["type"] != "order":
            continue
        ids: set[int] = set()
        mapping: dict[int, int] = {}
        for option in q["options"]:
            option_id = secrets.randbelow(2**53 - 1) + 1
            while option_id in ids:
                option_id = secrets.randbelow(2**53 - 1) + 1
            ids.add(option_id)
            mapping[option["id"]] = option_id
            option["id"] = option_id
        q["correct_order"] = [mapping[option_id] for option_id in q["correct_order"]]
    return snapshot


async def _open_room(
    db: AsyncSession, quiz_id: int, user: User, title: str, snapshot: list[dict[str, Any]], parent_id: int | None = None
) -> SessionCreatedOut:
    snapshot = _session_snapshot(snapshot)
    pin = manager.reserve_pin()
    gs = GameSession(
        quiz_id=quiz_id, host_id=user.id, pin=pin, title=title, snapshot=snapshot, parent_session_id=parent_id
    )
    try:
        db.add(gs)
        await db.commit()
        manager.create(gs.id, pin, user.id, title, snapshot, quiz_id=quiz_id)
    finally:
        manager.reserved_pins.discard(pin)
    return SessionCreatedOut(id=gs.id, pin=pin)


@router.post("", response_model=SessionCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_session(
    data: SessionCreateIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> SessionCreatedOut:
    quiz = await load_quiz(db, data.quiz_id, user)
    if quiz.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Запускать можно только свои викторины")
    if not quiz.questions:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "В викторине нет вопросов")
    return await _open_room(db, quiz.id, user, quiz.title, build_snapshot(quiz.questions))


@router.get("/history", response_model=list[SessionHistoryItem])
async def history(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    counts = select(Player.session_id, func.count(Player.id).label("n")).group_by(Player.session_id).subquery()
    rows = await db.execute(
        select(GameSession, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.session_id == GameSession.id)
        .where(GameSession.host_id == user.id)
        .order_by(GameSession.created_at.desc(), GameSession.id.desc())
        .limit(50)
    )
    return [
        SessionHistoryItem(
            id=gs.id,
            pin=gs.pin,
            title=gs.title,
            status=gs.status,
            created_at=gs.created_at,
            player_count=n,
            question_count=len(gs.snapshot),
            parent_session_id=gs.parent_session_id,
        )
        for gs, n in rows.all()
    ]


@router.get("/{pin}", response_model=SessionPublicOut)
async def session_by_pin(pin: str) -> SessionPublicOut:
    room = manager.get(pin)
    if room is None or room.state == FINISHED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Комната не найдена. Проверьте код")
    return SessionPublicOut(pin=pin, title=room.title, status=room.state, player_count=len(room.players))


@router.post("/{pin}/join", response_model=JoinOut, status_code=status.HTTP_201_CREATED)
async def join(pin: str, data: JoinIn, db: AsyncSession = Depends(get_db)) -> JoinOut:
    room = manager.get(pin)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Комната не найдена. Проверьте код")
    # Вход в две фазы: запись в базу идёт без lock комнаты, чтобы медленная база
    # не задерживала ответы игроков. Имя резервируется на это время.
    nick_key = data.nickname.casefold()
    async with room.lock:
        if room.state == FINISHED or manager.get(pin) is not room:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Комната закрыта")
        if room.nickname_taken(data.nickname):
            raise HTTPException(status.HTTP_409_CONFLICT, "Такое имя уже занято — добавьте букву или цифру")
        if len(room.players) + len(room.reserved_nicks) >= 200:
            raise HTTPException(status.HTTP_409_CONFLICT, "Комната заполнена")
        room.reserved_nicks.add(nick_key)
    try:
        token = secrets.token_urlsafe(24)
        avatar = data.avatar.model_dump()
        player = Player(session_id=room.session_id, nickname=data.nickname, avatar=avatar, token=token)
        db.add(player)
        try:
            await db.commit()
        except IntegrityError as e:
            await db.rollback()
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Комната закрыта") from e
        async with room.lock:
            if room.state == FINISHED or manager.get(pin) is not room:
                # Игра закончилась, пока шла запись: убираем строку, чтобы она не попала в отчёт.
                # (Если итоги уже сохранились, _persist удалил её сам.)
                await db.execute(delete(Player).where(Player.id == player.id))
                await db.commit()
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Комната закрыта")
            room.add_player(player.id, data.nickname, avatar, token)
            room.touch()
            await room.broadcast_lobby()
    finally:
        room.reserved_nicks.discard(nick_key)
    return JoinOut(player_id=player.id, token=token, nickname=data.nickname)


async def _own_session(db: AsyncSession, session_id: int, user: User) -> GameSession:
    gs = await db.scalar(
        select(GameSession)
        .where(GameSession.id == session_id)
        .options(selectinload(GameSession.players).selectinload(Player.answers))
    )
    if gs is None or gs.host_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Игра не найдена")
    return gs


@router.get("/{session_id}/report")
async def report(
    session_id: DbIdPath, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    gs = await _own_session(db, session_id, user)
    if gs.status == "aborted":
        raise HTTPException(status.HTTP_409_CONFLICT, "Игра была прервана, поэтому отчёта нет")
    if gs.status != "finished":
        raise HTTPException(status.HTTP_409_CONFLICT, "Отчёт появится, когда игра закончится")
    return build_report(gs)


def _was_shown(q: dict[str, Any]) -> bool:
    # В играх, сохранённых до появления отметок, считаем показанными все вопросы.
    return "eligible" in q or q.get("shown", True)


def build_report(gs: GameSession) -> dict[str, Any]:
    snap = gs.snapshot
    players = sorted(gs.players, key=lambda p: (p.final_rank or 10**6, p.nickname))
    everyone = {p.id for p in players}
    shown = [_was_shown(q) for q in snap]
    eligible = [set(q["eligible"]) & everyone if "eligible" in q else everyone for q in snap]
    questions = []
    for i, q in enumerate(snap):
        if not shown[i]:
            questions.append(
                {
                    "index": i,
                    "type": q["type"],
                    "text": q["text"],
                    "shown": False,
                    "eligible": 0,
                    "correct_rate": None,
                    "answered": 0,
                    "avg_ms": None,
                }
            )
            continue
        answers = [a for p in players if p.id in eligible[i] for a in p.answers if a.question_index == i]
        correct = sum(1 for a in answers if a.is_correct)
        n = len(eligible[i])
        questions.append(
            {
                "index": i,
                "type": q["type"],
                "text": q["text"],
                "shown": True,
                "eligible": n,
                "correct_rate": round(correct / n, 3) if n else None,
                "answered": len(answers),
                "avg_ms": round(sum(a.response_ms for a in answers) / len(answers)) if answers else None,
            }
        )
    rows = []
    for p in players:
        by_index = {a.question_index: a for a in p.answers}
        cells = []
        for i, q in enumerate(snap):
            a = by_index.get(i)
            if not shown[i]:
                state = "unshown"
            elif p.id not in eligible[i]:
                state = "absent"
            elif a is None:
                state = "none"
            elif not a.is_correct:
                state = "wrong"
            elif a.response_ms <= q["time_limit"] * 500:
                state = "fast"
            else:
                state = "slow"
            cells.append({"state": state, "points": a.points if a else 0})
        rows.append(
            {
                "id": p.id,
                "nickname": p.nickname,
                "avatar": p.avatar,
                "score": p.final_score,
                "rank": p.final_rank,
                "reconnects": p.reconnects,
                "correct": sum(1 for a in p.answers if a.is_correct),
                "asked": sum(1 for c in cells if c["state"] not in ("unshown", "absent")),
                "skipped": sum(1 for c in cells if c["state"] == "none"),
                "cells": cells,
            }
        )
    rated = [q for q in questions if q["correct_rate"] is not None]
    all_answers = [a for p in players for a in p.answers]
    hardest = min(rated, key=lambda q: q["correct_rate"]) if rated else None
    last = max((i for i, s in enumerate(shown) if s), default=None)
    return {
        "session": {
            "id": gs.id,
            "pin": gs.pin,
            "title": gs.title,
            "status": gs.status,
            "created_at": gs.created_at.isoformat() if gs.created_at else None,
            "finished_at": gs.finished_at.isoformat() if gs.finished_at else None,
            "player_count": len(players),
            "question_count": len(snap),
        },
        "summary": {
            "shown_count": sum(shown),
            "ended_early": not all(shown),
            "avg_correct_rate": round(sum(q["correct_rate"] for q in rated) / len(rated), 3) if rated else None,
            "hardest_index": hardest["index"] if hardest else None,
            "avg_response_ms": round(sum(a.response_ms for a in all_answers) / len(all_answers))
            if all_answers
            else None,
            "finished_count": sum(1 for p in players if any(a.question_index == last for a in p.answers))
            if last is not None
            else 0,
            "hard_rate": HARD_RATE,
            "retry_count": sum(1 for q in rated if q["correct_rate"] < HARD_RATE),
        },
        "questions": questions,
        "players": rows,
    }


@router.post("/{session_id}/retry", response_model=SessionCreatedOut, status_code=status.HTTP_201_CREATED)
async def retry_mistakes(
    session_id: DbIdPath, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> SessionCreatedOut:
    """Новая игра только из вопросов, на которые верно ответили меньше половины."""
    gs = await _own_session(db, session_id, user)
    if gs.status != "finished":
        raise HTTPException(status.HTTP_409_CONFLICT, "Сначала закончите игру")
    rep = build_report(gs)
    hard = [q["index"] for q in rep["questions"] if q["correct_rate"] is not None and q["correct_rate"] < HARD_RATE]
    if not hard:
        if not any(q["correct_rate"] is not None for q in rep["questions"]):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "В игре не было участников — повторять нечего")
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Трудных вопросов нет: везде верно ответили не меньше половины"
        )
    quiz_exists = await db.scalar(select(Quiz.id).where(Quiz.id == gs.quiz_id))
    if quiz_exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Исходная викторина удалена")
    snapshot = [gs.snapshot[i] for i in hard]  # отметки отчёта снимет _session_snapshot
    suffix = " · работа над ошибками"
    title = gs.title if gs.title.endswith(suffix) else f"{gs.title}{suffix}"
    return await _open_room(db, gs.quiz_id, user, title[:120], snapshot, parent_id=gs.id)
