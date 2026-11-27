from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import LoginIn, PasswordChangeIn, RegisterIn, TokenOut, UserOut
from app.security import DUMMY_HASH, create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _token(user: User) -> TokenOut:
    return TokenOut(access_token=create_access_token(user.id, user.token_version), user=UserOut.model_validate(user))


async def _check_password(request: Request, password: str, password_hash: str) -> bool:
    limiter = request.app.state.password_limiter
    return await to_thread.run_sync(verify_password, password, password_hash, limiter=limiter)


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterIn, request: Request, db: AsyncSession = Depends(get_db)) -> TokenOut:
    request.app.state.rate_limit.check(request, "register")
    email = data.email.lower()
    exists = await db.scalar(select(User.id).where(User.email == email))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Этот email уже зарегистрирован")
    password_hash = await to_thread.run_sync(hash_password, data.password, limiter=request.app.state.password_limiter)
    user = User(email=email, username=data.username, password_hash=password_hash, token_version=0)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Этот email уже зарегистрирован") from e
    return _token(user)


@router.post("/login", response_model=TokenOut)
async def login(data: LoginIn, request: Request, db: AsyncSession = Depends(get_db)) -> TokenOut:
    request.app.state.rate_limit.check(request, "login")
    user = await db.scalar(select(User).where(User.email == data.email.lower()))
    # Неизвестный email тоже проходит проверку пароля — по времени ответа его не отличить от известного.
    valid = await _check_password(request, data.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not valid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный email или пароль")
    return _token(user)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/password", response_model=TokenOut)
async def change_password(
    data: PasswordChangeIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TokenOut:
    """Смена пароля. Все прежние входы (другие устройства, украденный токен) перестают действовать."""
    request.app.state.rate_limit.check(request, "login")
    if not await _check_password(request, data.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Текущий пароль указан неверно")
    user.password_hash = await to_thread.run_sync(
        hash_password, data.password, limiter=request.app.state.password_limiter
    )
    user.token_version += 1
    await db.commit()
    return _token(user)  # это устройство остаётся в системе с новым токеном


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> Response:
    """Выйти на всех устройствах: все выданные токены перестают действовать."""
    user.token_version += 1
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
