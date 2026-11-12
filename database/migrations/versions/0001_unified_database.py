"""Create the unified ICLR database.

Revision ID: 0001
Revises:
"""
from pathlib import Path

from alembic import op


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    schema = Path(__file__).resolve().parents[2] / "schema.sql"
    op.get_bind().connection.driver_connection.execute(schema.read_text(encoding="utf-8"))


def downgrade() -> None:
    connection = op.get_bind().connection.driver_connection
    connection.execute("DROP SCHEMA IF EXISTS twin CASCADE")
    connection.execute("DROP SCHEMA IF EXISTS semantic CASCADE")
    connection.execute("DROP SCHEMA IF EXISTS core CASCADE")
    connection.execute("DROP SCHEMA IF EXISTS raw CASCADE")
    connection.execute("DROP SCHEMA IF EXISTS ops CASCADE")
