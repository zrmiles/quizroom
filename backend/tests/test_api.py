from tests.conftest import SAMPLE_QUIZ, register


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_register_login_me(client):
    acc = register(client, "Анна")
    r = client.post("/api/auth/login", json={"email": acc["email"].upper(), "password": "password123"})
    assert r.status_code == 200
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.json()["username"] == "Анна"


def test_duplicate_email_conflict(client):
    acc = register(client)
    r = client.post("/api/auth/register", json={"email": acc["email"], "username": "x2", "password": "password123"})
    assert r.status_code == 409


def test_wrong_password(client):
    acc = register(client)
    r = client.post("/api/auth/login", json={"email": acc["email"], "password": "wrong-password"})
    assert r.status_code == 401


def test_quizzes_need_auth(client):
    assert client.get("/api/quizzes").status_code == 401


def test_quiz_crud(client, host, quiz):
    assert [q["type"] for q in quiz["questions"]] == ["single", "number", "order"]
    listing = client.get("/api/quizzes", headers=host["headers"]).json()
    assert listing[0]["question_count"] == 3

    updated = {**SAMPLE_QUIZ, "title": "Новое название", "questions": SAMPLE_QUIZ["questions"][:1]}
    r = client.put(f"/api/quizzes/{quiz['id']}", json=updated, headers=host["headers"])
    assert r.status_code == 200
    assert r.json()["title"] == "Новое название"
    assert len(r.json()["questions"]) == 1

    assert client.delete(f"/api/quizzes/{quiz['id']}", headers=host["headers"]).status_code == 204
    assert client.get(f"/api/quizzes/{quiz['id']}", headers=host["headers"]).status_code == 404


def test_single_question_requires_one_correct(client, host):
    bad = {"title": "Т", "questions": [{"type": "single", "text": "Вопрос", "options": [{"text": "а"}, {"text": "б"}]}]}
    r = client.post("/api/quizzes", json=bad, headers=host["headers"])
    assert r.status_code == 422


def test_number_answer_must_be_on_scale(client, host):
    bad = {
        "title": "Т",
        "questions": [
            {
                "type": "number",
                "text": "Год?",
                "number_answer": 3000,
                "number_min": 1900,
                "number_max": 2000,
                "number_tolerance": 10,
            }
        ],
    }
    assert client.post("/api/quizzes", json=bad, headers=host["headers"]).status_code == 422


def test_cannot_edit_someone_elses_quiz(client, quiz):
    other = register(client, "Чужой")
    r = client.put(f"/api/quizzes/{quiz['id']}", json=SAMPLE_QUIZ, headers=other["headers"])
    assert r.status_code == 404
    assert client.delete(f"/api/quizzes/{quiz['id']}", headers=other["headers"]).status_code == 403


def test_unknown_pin(client):
    assert client.get("/api/sessions/000000").status_code in (404,)
