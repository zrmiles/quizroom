"""Учётные записи ведущих: смена пароля, отзыв входа, неразличимость email при входе."""

from unittest.mock import patch

import pytest
from starlette.websockets import WebSocketDisconnect

from app.routers.ws import DENIED_CODE
from tests.conftest import SAMPLE_QUIZ, game_ws, register
from tests.test_game import open_game, recv_until


def test_change_password_revokes_other_sessions_and_keeps_this_one(client):
    me = register(client)
    other_device = dict(me["headers"])
    r = client.post(
        "/api/auth/password",
        json={"current_password": "password123", "password": "new-password-456"},
        headers=me["headers"],
    )
    assert r.status_code == 200
    fresh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=fresh).status_code == 200
    assert client.get("/api/auth/me", headers=other_device).status_code == 401
    old = client.post("/api/auth/login", json={"email": me["email"], "password": "password123"})
    new = client.post("/api/auth/login", json={"email": me["email"], "password": "new-password-456"})
    assert old.status_code == 401 and new.status_code == 200


def test_change_password_requires_current_one(client):
    me = register(client)
    r = client.post(
        "/api/auth/password",
        json={"current_password": "wrong-password", "password": "new-password-456"},
        headers=me["headers"],
    )
    assert r.status_code == 400
    assert client.get("/api/auth/me", headers=me["headers"]).status_code == 200


def test_logout_everywhere_also_closes_host_room_access(client, host):
    quiz = client.post("/api/quizzes", json=SAMPLE_QUIZ, headers=host["headers"]).json()
    _, pin = open_game(client, host, quiz)
    assert client.post("/api/auth/logout-all", headers=host["headers"]).status_code == 204
    assert client.get("/api/quizzes", headers=host["headers"]).status_code == 401
    with game_ws(client, pin, host["token"], "host") as ws:
        recv_until(ws, "error")
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == DENIED_CODE


def test_unknown_email_also_checks_a_password_hash(client):
    """Время ответа не должно выдавать, зарегистрирован ли email."""
    me = register(client)
    with patch("app.routers.auth.verify_password", return_value=False) as check:
        client.post("/api/auth/login", json={"email": me["email"], "password": "wrong-password"})
        client.post("/api/auth/login", json={"email": "nobody-" + me["email"], "password": "wrong-password"})
    assert check.call_count == 2


def test_tokens_issued_before_versions_still_work(client):
    import jwt

    from app.config import settings

    me = register(client)
    legacy = jwt.encode({"sub": str(me["user"]["id"]), "exp": 4102444800}, settings.jwt_secret, algorithm="HS256")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {legacy}"}).status_code == 200


def test_deleting_quiz_keeps_finished_games_and_reports(client, host):
    quiz = client.post("/api/quizzes", json=SAMPLE_QUIZ, headers=host["headers"]).json()
    sid, pin = open_game(client, host, quiz)
    me = client.post(f"/api/sessions/{pin}/join", json={"nickname": "Аня"}).json()
    with game_ws(client, pin, host["token"], "host") as h, game_ws(client, pin, me["token"]) as p:
        recv_until(h, "state:snapshot")
        recv_until(p, "state:snapshot")
        h.send_json({"type": "host:start"})
        recv_until(p, "question:start")
        h.send_json({"type": "host:end"})
        recv_until(h, "game:finished")
    assert client.delete(f"/api/quizzes/{quiz['id']}", headers=host["headers"]).status_code == 204
    assert client.get(f"/api/sessions/{sid}/report", headers=host["headers"]).status_code == 200
    assert any(h["id"] == sid for h in client.get("/api/sessions/history", headers=host["headers"]).json())
    retry = client.post(f"/api/sessions/{sid}/retry", headers=host["headers"])
    assert retry.status_code in (400, 404)


def test_quiz_list_counts_questions(client, host):
    client.post("/api/quizzes", json=SAMPLE_QUIZ, headers=host["headers"])
    client.post("/api/quizzes", json={**SAMPLE_QUIZ, "title": "Пустая", "questions": []}, headers=host["headers"])
    counts = {q["title"]: q["question_count"] for q in client.get("/api/quizzes", headers=host["headers"]).json()}
    assert counts == {SAMPLE_QUIZ["title"]: 3, "Пустая": 0}


def test_quizzes_are_never_shared_even_if_flagged_public(client, host):
    quiz = client.post("/api/quizzes", json={**SAMPLE_QUIZ, "is_public": True}, headers=host["headers"]).json()
    assert quiz["is_public"] is False
    stranger = register(client, "Чужой")
    assert client.get(f"/api/quizzes/{quiz['id']}", headers=stranger["headers"]).status_code == 404
