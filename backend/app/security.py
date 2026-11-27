import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    if len(password.encode()) > 72:
        return False
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


# Хеш случайного пароля: вход с неизвестным email проверяет его, чтобы ответ шёл столько же,
# сколько для существующего. Иначе по времени ответа можно узнать, зарегистрирован ли адрес.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def create_access_token(user_id: int, version: int = 0) -> str:
    expires = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "ver": version, "exp": expires}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> tuple[int, int] | None:
    """ID пользователя и версия токена. Токены, выданные до появления версий, считаются версией 0."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        version = payload.get("ver", 0)
        if not isinstance(version, int):
            return None
        return int(payload["sub"]), version
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None
