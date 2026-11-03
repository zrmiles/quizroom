from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictInt, TypeAdapter, field_validator, model_validator

QuestionType = Literal["single", "number", "order"]
Shape = Literal["round", "blob", "box"]

AVATAR_COLORS = {"#FF7A59", "#FFD23F", "#5BD9A0", "#9B8CFF", "#4CC9F0", "#FF8FC7"}

# Конечное число разумного размера: Infinity/NaN ломают JSON-ответ и сохраняют «битую» викторину.
FiniteNumber = Annotated[float, Field(allow_inf_nan=False, ge=-1e12, le=1e12)]


def _strip_required(v: str, message: str) -> str:
    v = " ".join(v.split())
    if not v:
        raise ValueError(message)
    return v


# ---------- Auth ----------


class PasswordIn(BaseModel):
    password: str = Field(max_length=72)

    @field_validator("password")
    @classmethod
    def password_bytes(cls, v: str) -> str:
        if len(v.encode()) > 72:
            raise ValueError("Пароль слишком длинный: не более 72 байт UTF-8")
        return v


class RegisterIn(PasswordIn):
    email: EmailStr
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=8, max_length=72)

    @field_validator("username")
    @classmethod
    def clean_username(cls, v: str) -> str:
        v = _strip_required(v, "Введите имя")
        if len(v) < 2:
            raise ValueError("Имя — от 2 символов")
        return v


class LoginIn(PasswordIn):
    email: EmailStr


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    username: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- Викторины ----------


class OptionIn(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    is_correct: bool = False

    @field_validator("text")
    @classmethod
    def strip_text(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Пустой вариант ответа")
        return v


class QuestionIn(BaseModel):
    type: QuestionType
    text: str = Field(min_length=1, max_length=500)
    time_limit: int = Field(default=20, ge=5, le=120)
    options: list[OptionIn] = []
    number_answer: FiniteNumber | None = None
    number_min: FiniteNumber | None = None
    number_max: FiniteNumber | None = None
    number_tolerance: FiniteNumber | None = None
    number_exact_bonus: bool = False

    @model_validator(mode="after")
    def check_by_type(self) -> "QuestionIn":
        self.text = self.text.strip()
        if not self.text:
            raise ValueError("Добавьте текст вопроса")
        if self.type == "single":
            if not 2 <= len(self.options) <= 4:
                raise ValueError("Нужно от 2 до 4 вариантов")
            if sum(o.is_correct for o in self.options) != 1:
                raise ValueError("Отметьте ровно один верный вариант")
        elif self.type == "number":
            vals = (self.number_answer, self.number_min, self.number_max, self.number_tolerance)
            if any(v is None for v in vals):
                raise ValueError("Заполните ответ, шкалу и допуск")
            if not self.number_min < self.number_max:  # type: ignore[operator]
                raise ValueError("«От» должно быть меньше «до»")
            if not self.number_min <= self.number_answer <= self.number_max:  # type: ignore[operator]
                raise ValueError("Ответ вне шкалы")
            if self.number_tolerance <= 0:  # type: ignore[operator]
                raise ValueError("Допуск должен быть больше нуля")
            self.options = []
        elif self.type == "order":
            if not 3 <= len(self.options) <= 6:
                raise ValueError("Нужно от 3 до 6 элементов")
            for o in self.options:
                o.is_correct = False
        return self


class QuizIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    is_public: bool = False
    questions: list[QuestionIn] = Field(default=[], max_length=50)

    @field_validator("title")
    @classmethod
    def clean_title(cls, v: str) -> str:
        return _strip_required(v, "Дайте викторине название")


class OptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str
    is_correct: bool


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: QuestionType
    text: str
    time_limit: int
    options: list[OptionOut]
    number_answer: float | None
    number_min: float | None
    number_max: float | None
    number_tolerance: float | None
    number_exact_bonus: bool


class QuizOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    is_public: bool
    updated_at: datetime
    questions: list[QuestionOut]


class QuizSummary(BaseModel):
    id: int
    title: str
    question_count: int
    updated_at: datetime


# ---------- Игровые сессии ----------


class Avatar(BaseModel):
    shape: Shape = "round"
    color: str = "#FF7A59"
    eyes: int = Field(default=2, ge=1, le=3)

    @field_validator("color")
    @classmethod
    def known_color(cls, v: str) -> str:
        v = v.upper()
        if v not in AVATAR_COLORS:
            raise ValueError("Неизвестный цвет")
        return v


class SessionCreateIn(BaseModel):
    quiz_id: int


class SessionCreatedOut(BaseModel):
    id: int
    pin: str


class SessionPublicOut(BaseModel):
    pin: str
    title: str
    status: str
    player_count: int


class JoinIn(BaseModel):
    nickname: str = Field(min_length=1, max_length=16)
    avatar: Avatar = Avatar()

    @field_validator("nickname")
    @classmethod
    def strip_nick(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Введите имя")
        return v


class JoinOut(BaseModel):
    player_id: int
    token: str
    nickname: str


class SessionHistoryItem(BaseModel):
    id: int
    pin: str
    title: str
    status: str
    created_at: datetime
    player_count: int
    question_count: int
    parent_session_id: int | None


# WebSocket-команды и ответы проверяются независимо от REST-схем.
class StrictMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HostCommand(StrictMessage):
    type: Literal["host:start", "host:next", "host:skip", "host:end"]


class KickCommand(StrictMessage):
    type: Literal["host:kick"]
    player_id: StrictInt


class AnswerCommand(StrictMessage):
    type: Literal["player:answer"]
    questionIndex: StrictInt = Field(ge=0)
    value: dict


class WaveCommand(StrictMessage):
    type: Literal["player:wave"]


GAME_COMMAND = TypeAdapter(
    Annotated[HostCommand | KickCommand | AnswerCommand | WaveCommand, Field(discriminator="type")]
)


class SingleAnswer(StrictMessage):
    option_id: StrictInt


class NumberAnswer(StrictMessage):
    number: Annotated[float, Field(strict=True, allow_inf_nan=False, ge=-1e12, le=1e12)]


class OrderAnswer(StrictMessage):
    order: list[StrictInt] = Field(max_length=6)


ANSWER_SCHEMAS = {"single": SingleAnswer, "number": NumberAnswer, "order": OrderAnswer}
