"""Начальная схема — та, что раньше создавалась через create_all.

Базы, созданные до появления миграций, помечаются этой ревизией без изменений (см. app.db.init_db).

Revision ID: 0001
Revises:
Create Date: 2026-11-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("username", sa.String(40), nullable=False),
        sa.Column("password_hash", sa.String(100), nullable=False),
        _created_at(),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "quizzes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        _created_at(),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_quizzes_owner_id", "quizzes", ["owner_id"])

    op.create_table(
        "questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("quiz_id", sa.Integer(), sa.ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("time_limit", sa.Integer(), nullable=False),
        sa.Column("number_answer", sa.Float(), nullable=True),
        sa.Column("number_min", sa.Float(), nullable=True),
        sa.Column("number_max", sa.Float(), nullable=True),
        sa.Column("number_tolerance", sa.Float(), nullable=True),
        sa.Column("number_exact_bonus", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_questions_quiz_id", "questions", ["quiz_id"])

    op.create_table(
        "answer_options",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(200), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_answer_options_question_id", "answer_options", ["question_id"])

    op.create_table(
        "game_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("quiz_id", sa.Integer(), sa.ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("host_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pin", sa.String(6), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "parent_session_id",
            sa.Integer(),
            sa.ForeignKey("game_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _created_at(),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_game_sessions_quiz_id", "game_sessions", ["quiz_id"])
    op.create_index("ix_game_sessions_host_id", "game_sessions", ["host_id"])
    op.create_index("ix_game_sessions_pin", "game_sessions", ["pin"])

    op.create_table(
        "players",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("game_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("nickname", sa.String(16), nullable=False),
        sa.Column("avatar", sa.JSON(), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("final_score", sa.Integer(), nullable=False),
        sa.Column("final_rank", sa.Integer(), nullable=True),
        sa.Column("reconnects", sa.Integer(), nullable=False),
    )
    op.create_index("ix_players_session_id", "players", ["session_id"])
    op.create_index("ix_players_token", "players", ["token"], unique=True)

    op.create_table(
        "player_answers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_index", sa.Integer(), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("response_ms", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("player_id", "question_index"),
    )
    op.create_index("ix_player_answers_player_id", "player_answers", ["player_id"])


def downgrade() -> None:
    for table in ("player_answers", "players", "game_sessions", "answer_options", "questions", "quizzes", "users"):
        op.drop_table(table)
