"""Record database snapshot artifact metadata.

Revision ID: 0003
Revises: 0002
"""
from alembic import op


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE ops.dataset_snapshot ADD COLUMN dump_path TEXT;
        ALTER TABLE ops.dataset_snapshot ADD COLUMN dump_sha256 CHAR(64);
        ALTER TABLE ops.dataset_snapshot ADD COLUMN restore_command TEXT;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE ops.dataset_snapshot DROP COLUMN restore_command;
        ALTER TABLE ops.dataset_snapshot DROP COLUMN dump_sha256;
        ALTER TABLE ops.dataset_snapshot DROP COLUMN dump_path;
    """)
