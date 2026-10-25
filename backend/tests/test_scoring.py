import pytest

from app.game.scoring import score, speed_factor

SINGLE = {"type": "single", "time_limit": 20, "options": [{"id": 1}, {"id": 2}], "correct_option_id": 1}
NUMBER = {
    "type": "number",
    "time_limit": 20,
    "answer": 1961,
    "min": 1900,
    "max": 2000,
    "tolerance": 20,
    "exact_bonus": True,
    "options": [],
}
ORDER = {"type": "order", "time_limit": 30, "correct_order": [10, 11, 12, 13], "options": []}


def test_speed_factor_bounds():
    assert speed_factor(0, 20) == 1.0
    assert speed_factor(20_000, 20) == 0.5
    assert speed_factor(99_999, 20) == 0.5  # после лимита не меньше половины
    assert speed_factor(-5, 20) == 1.0


def test_single_correct_fast_gets_1000():
    assert score(SINGLE, {"option_id": 1}, 0) == (True, 1000)


def test_single_correct_at_deadline_gets_500():
    assert score(SINGLE, {"option_id": 1}, 20_000) == (True, 500)


def test_single_wrong_gets_zero():
    assert score(SINGLE, {"option_id": 2}, 100) == (False, 0)


def test_single_unknown_option_rejected():
    with pytest.raises(ValueError):
        score(SINGLE, {"option_id": 99}, 0)


def test_number_exact_doubles():
    assert score(NUMBER, {"number": 1961}, 0) == (True, 2000)


def test_number_close_gets_partial():
    correct, points = score(NUMBER, {"number": 1958}, 0)  # ошибка 3 из 20 → 85%
    assert correct and points == 850


def test_number_beyond_tolerance_gets_zero():
    assert score(NUMBER, {"number": 1985}, 0) == (False, 0)


def test_number_outside_scale_rejected():
    with pytest.raises(ValueError):
        score(NUMBER, {"number": 2500}, 0)


def test_number_rejects_non_numbers():
    with pytest.raises(ValueError):
        score(NUMBER, {"number": "1961"}, 0)
    with pytest.raises(ValueError):
        score(NUMBER, {"number": True}, 0)


def test_order_full():
    assert score(ORDER, {"order": [10, 11, 12, 13]}, 0) == (True, 1000)


def test_order_partial_counts_items_in_place():
    correct, points = score(ORDER, {"order": [10, 12, 11, 13]}, 0)  # 2 из 4 на месте
    assert not correct and points == 500


def test_order_must_contain_all_items():
    with pytest.raises(ValueError):
        score(ORDER, {"order": [10, 11, 12]}, 0)
