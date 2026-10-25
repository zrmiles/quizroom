import os
import tempfile
import uuid

# Отдельная SQLite-база для тестов — до импорта приложения.
_tmp = tempfile.mkdtemp(prefix="quizroom-test-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp}/test.db"
os.environ["JWT_SECRET"] = "test-secret"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def register(client: TestClient, name: str = "Учитель") -> dict:
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/auth/register", json={"email": email, "username": name, "password": "password123"})
    assert r.status_code == 201, r.text
    body = r.json()
    return {
        "token": body["access_token"],
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "email": email,
        "user": body["user"],
    }


SAMPLE_QUIZ = {
    "title": "Астрономия для 7Б",
    "description": "",
    "questions": [
        {
            "type": "single",
            "text": "Какая планета самая большая в Солнечной системе?",
            "time_limit": 20,
            "options": [
                {"text": "Юпитер", "is_correct": True},
                {"text": "Сатурн"},
                {"text": "Нептун"},
                {"text": "Земля"},
            ],
        },
        {
            "type": "number",
            "text": "В каком году человек впервые полетел в космос?",
            "time_limit": 20,
            "number_answer": 1961,
            "number_min": 1900,
            "number_max": 2000,
            "number_tolerance": 20,
            "number_exact_bonus": True,
        },
        {
            "type": "order",
            "text": "Расставьте планеты по размеру — от самой большой",
            "time_limit": 30,
            "options": [{"text": "Юпитер"}, {"text": "Нептун"}, {"text": "Земля"}, {"text": "Марс"}],
        },
    ],
}


@pytest.fixture
def host(client):
    return register(client)


@pytest.fixture
def quiz(client, host):
    r = client.post("/api/quizzes", json=SAMPLE_QUIZ, headers=host["headers"])
    assert r.status_code == 201, r.text
    return r.json()
