from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import LoginIn, RegisterIn, TokenOut, UserOut
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterIn, request: Request, db: AsyncSession = Depends(get_db)) -> TokenOut:
    request.app.state.rate_limit.check(request, "register")
    email = data.email.lower()
    exists = await db.scalar(select(User.id).where(User.email == email))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Этот email уже зарегистрирован")
    password_hash = await to_thread.run_sync(hash_password, data.password, limiter=request.app.state.password_limiter)
    user = User(email=email, username=data.username.strip(), password_hash=password_hash)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Этот email уже зарегистрирован") from e
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
async def login(data: LoginIn, request: Request, db: AsyncSession = Depends(get_db)) -> TokenOut:
    request.app.state.rate_limit.check(request, "login")
    user = await db.scalar(select(User).where(User.email == data.email.lower()))
    valid = user is not None and await to_thread.run_sync(
        verify_password, data.password, user.password_hash, limiter=request.app.state.password_limiter
    )
    if not valid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный email или пароль")
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user
