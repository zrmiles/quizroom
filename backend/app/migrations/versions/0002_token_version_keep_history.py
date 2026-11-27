"""Версия токена у пользователя; игры остаются в истории после удаления викторины.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Внешний ключ создавался без имени. PostgreSQL назвал его сам; в SQLite имени нет,
# поэтому при пересоздании таблицы Alembic даёт ему имя по этому шаблону.
SQLITE_NAMES = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def _quiz_fk(ondelete: str, nullable: bool) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("game_sessions", naming_convention=SQLITE_NAMES) as batch:
            batch.drop_constraint("fk_game_sessions_quiz_id_quizzes", type_="foreignkey")
            batch.alter_column("quiz_id", existing_type=sa.Integer(), nullable=nullable)
            batch.create_foreign_key(
                "fk_game_sessions_quiz_id_quizzes", "quizzes", ["quiz_id"], ["id"], ondelete=ondelete
            )
        return
    op.drop_constraint("game_sessions_quiz_id_fkey", "game_sessions", type_="foreignkey")
    op.alter_column("game_sessions", "quiz_id", existing_type=sa.Integer(), nullable=nullable)
    op.create_foreign_key(
        "game_sessions_quiz_id_fkey", "game_sessions", "quizzes", ["quiz_id"], ["id"], ondelete=ondelete
    )


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("token_version", sa.Integer(), server_default="0", nullable=False))
    _quiz_fk("SET NULL", nullable=True)


def downgrade() -> None:
    # Игры удалённых викторин некуда привязать — при откате они удаляются, как было раньше.
    op.execute("DELETE FROM game_sessions WHERE quiz_id IS NULL")
    _quiz_fk("CASCADE", nullable=False)
    with op.batch_alter_table("users") as batch:
        batch.drop_column("token_version")
