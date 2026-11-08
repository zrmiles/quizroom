"""Мелкие находки аудита готовности от 5 ноября: R07, R11, R23."""

import pytest

from app.game.scoring import is_exact, score
from tests.conftest import SAMPLE_QUIZ


def _payload(quiz: dict, **changes) -> dict:
    body = {k: quiz[k] for k in ("title", "description", "is_public")}
    body["questions"] = [
        {k: v for k, v in q.items() if k not in ("id", "position")}
        | {"options": [{"text": o["text"], "is_correct": o["is_correct"]} for o in q["options"]]}
        for q in quiz["questions"]
    ]
    return body | changes


# ---------- R07: две вкладки не затирают правки друг друга ----------


def test_stale_tab_gets_conflict_instead_of_overwriting(client, host, quiz):
    url, h = f"/api/quizzes/{quiz['id']}", host["headers"]
    base = quiz["updated_at"]
    tab_a = _payload(quiz, base_updated_at=base)
    tab_a["questions"][0]["text"] = "Правка из вкладки A"
    saved = client.put(url, json=tab_a, headers=h)
    assert saved.status_code == 200
    assert saved.json()["updated_at"] != base

    tab_b = _payload(quiz, title="Заголовок из вкладки B", base_updated_at=base)
    r = client.put(url, json=tab_b, headers=h)
    assert r.status_code == 409 and "другой вкладке" in r.json()["detail"]
    assert client.get(url, headers=h).json()["questions"][0]["text"] == "Правка из вкладки A"

    # Вкладка с актуальной версией сохраняет спокойно, клиент без версии — тоже (поверх).
    fresh = _payload(saved.json(), title="Новый заголовок", base_updated_at=saved.json()["updated_at"])
    assert client.put(url, json=fresh, headers=h).status_code == 200
    assert client.put(url, json=_payload(quiz, title="Поверх"), headers=h).status_code == 200


# ---------- R11: точность и однозначность ----------


def test_exact_on_large_numbers_matches_points():
    assert not is_exact(999999999999 - 0.4998779296875, 999999999999, 0.5)
    assert is_exact(0.1 + 0.2, 0.3, 1)
    q = {
        "type": "number",
        "time_limit": 20,
        "answer": 999999999999,
        "min": 0,
        "max": 1e12,
        "tolerance": 0.5,
        "exact_bonus": True,
        "options": [],
    }
    assert score(q, {"number": 999999999999}, 0) == (True, 2000)
    correct, points = score(q, {"number": 999999999999 - 0.4998779296875}, 0)
    assert not correct and points == 0


@pytest.mark.parametrize("index", [0, 2])
def test_duplicate_options_are_rejected(client, host, index):
    body = {**SAMPLE_QUIZ, "questions": [dict(q) for q in SAMPLE_QUIZ["questions"]]}
    q = body["questions"][index]
    q["options"] = [dict(o) for o in q["options"]]
    q["options"][1]["text"] = "  " + q["options"][0]["text"].upper() + " "
    r = client.post("/api/quizzes", json=body, headers=host["headers"])
    assert r.status_code == 422
    assert "повторяться" in r.text


# ---------- R23: огромные ID ----------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/quizzes/{big}", None),
        ("delete", "/api/quizzes/{big}", None),
        ("get", "/api/sessions/{big}/report", None),
        ("post", "/api/sessions/{big}/retry", None),
        ("post", "/api/sessions", {"quiz_id": "big"}),
    ],
)
def test_huge_ids_are_validation_errors(client, host, method, path, body):
    big = 10**40
    kwargs = {"headers": host["headers"]}
    if body is not None:
        kwargs["json"] = {"quiz_id": big}
    r = client.request(method.upper(), path.format(big=big), **kwargs)
    assert r.status_code == 422
