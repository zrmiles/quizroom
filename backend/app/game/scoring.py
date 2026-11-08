"""Подсчёт очков. Чистые функции — их легко покрыть unit-тестами.

Вопрос здесь — словарь из snapshot сессии (см. sessions.build_snapshot).
"""

from typing import Any

from pydantic import ValidationError

from app.schemas import ANSWER_SCHEMAS

MAX_POINTS = 1000


def speed_factor(response_ms: int, time_limit_s: int) -> float:
    """1.0 при мгновенном ответе, 0.5 — в последнюю секунду."""
    limit_ms = max(time_limit_s, 1) * 1000
    t = min(max(response_ms, 0), limit_ms) / limit_ms
    return 1 - 0.5 * t


def is_exact(guess: float, answer: float, tolerance: float) -> bool:
    """Точное попадание — единое правило для бонуса, флага `exact` и сообщения игроку.

    Допускаем только погрешность записи дробей (0.1 + 0.2 против 0.3): отклонение не больше
    миллиардной доли допуска. На больших числах относительное сравнение признало бы
    «точным» ответ, который почти на весь допуск мимо.
    """
    return guess == answer or abs(guess - answer) <= tolerance * 1e-9


def score_single(q: dict[str, Any], value: dict[str, Any], response_ms: int) -> tuple[bool, int]:
    option_id = value.get("option_id")
    valid_ids = {o["id"] for o in q["options"]}
    if option_id not in valid_ids:
        raise ValueError("Нет такого варианта")
    correct = option_id == q["correct_option_id"]
    points = round(MAX_POINTS * speed_factor(response_ms, q["time_limit"])) if correct else 0
    return correct, points


def score_number(q: dict[str, Any], value: dict[str, Any], response_ms: int) -> tuple[bool, int]:
    raw = value.get("number")
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ValueError("Ответ должен быть числом")
    guess = float(raw)
    if not q["min"] <= guess <= q["max"]:
        raise ValueError("Ответ вне шкалы")
    diff = abs(guess - q["answer"])
    closeness = max(0.0, 1 - diff / q["tolerance"])
    points = MAX_POINTS * speed_factor(response_ms, q["time_limit"]) * closeness
    if q["exact_bonus"] and is_exact(guess, q["answer"], q["tolerance"]):
        points *= 2
    points_int = round(points)
    return points_int > 0, points_int


def score_order(q: dict[str, Any], value: dict[str, Any], response_ms: int) -> tuple[bool, int]:
    order = value.get("order")
    correct_order: list[int] = q["correct_order"]
    if not isinstance(order, list) or sorted(order) != sorted(correct_order):
        raise ValueError("Нужно расставить все элементы")
    hits = sum(1 for a, b in zip(order, correct_order, strict=True) if a == b)
    share = hits / len(correct_order)
    points = round(MAX_POINTS * share * speed_factor(response_ms, q["time_limit"]))
    return hits == len(correct_order), points


SCORERS = {"single": score_single, "number": score_number, "order": score_order}


def score(q: dict[str, Any], value: dict[str, Any], response_ms: int) -> tuple[bool, int]:
    if not isinstance(value, dict):
        raise ValueError("Неверный формат ответа")
    try:
        value = ANSWER_SCHEMAS[q["type"]].model_validate(value).model_dump()
    except ValidationError as e:
        raise ValueError("Неверный формат ответа") from e
    return SCORERS[q["type"]](q, value, response_ms)
