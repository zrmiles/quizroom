from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User
from app.security import decode_access_token

bearer = HTTPBearer(auto_error=False)


async def user_from_token(db: AsyncSession, token: str) -> User | None:
    """Пользователь по JWT; None — токен недействителен, истёк или отозван сменой пароля / «выйти везде»."""
    decoded = decode_access_token(token)
    if decoded is None:
        return None
    user_id, version = decoded
    user = await db.get(User, user_id)
    if user is None or user.token_version != version:
        return None
    return user


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужно войти")
    user = await user_from_token(db, creds.credentials)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия истекла, войдите снова")
    return user
