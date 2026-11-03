from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки берутся из переменных окружения (или файла .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./quizroom.db"
    jwt_secret: str = Field(min_length=32)
    jwt_expire_minutes: int = 60 * 24 * 7
    cors_origins: list[str] = ["http://localhost:5173"]
    # Сколько миллисекунд после конца таймера ещё принимаем ответ (сетевая задержка).
    answer_grace_ms: int = 300

    @field_validator("jwt_secret")
    @classmethod
    def secure_secret(cls, value: str) -> str:
        if len(value.strip()) < 32 or value == "dev-secret-change-me":
            raise ValueError("Задайте случайный JWT_SECRET длиной не менее 32 символов")
        return value


settings = Settings()
