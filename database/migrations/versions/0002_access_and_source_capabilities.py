"""Add access grants and source capability reporting.

Revision ID: 0002
Revises: 0001
"""
from alembic import op


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ops.source_capability (
            capability_key TEXT PRIMARY KEY,
            available BOOLEAN NOT NULL,
            checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            details JSONB NOT NULL DEFAULT '{}'::jsonb
        );

        GRANT USAGE ON SCHEMA raw, core, semantic, twin, ops TO iclr_readonly, iclr_app, iclr_ingest;
        GRANT SELECT ON ALL TABLES IN SCHEMA raw, core, semantic, twin, ops TO iclr_readonly;
        GRANT SELECT ON ALL TABLES IN SCHEMA raw, core, semantic, twin, ops TO iclr_app, iclr_ingest;
        GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA raw, core, ops TO iclr_ingest;
        GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA semantic, twin, ops TO iclr_app;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA raw, core, semantic, twin, ops TO iclr_ingest, iclr_app;

        ALTER DEFAULT PRIVILEGES IN SCHEMA raw GRANT SELECT ON TABLES TO iclr_readonly;
        ALTER DEFAULT PRIVILEGES IN SCHEMA core GRANT SELECT ON TABLES TO iclr_readonly;
        ALTER DEFAULT PRIVILEGES IN SCHEMA semantic GRANT SELECT ON TABLES TO iclr_readonly;
        ALTER DEFAULT PRIVILEGES IN SCHEMA twin GRANT SELECT ON TABLES TO iclr_readonly;
        ALTER DEFAULT PRIVILEGES IN SCHEMA ops GRANT SELECT ON TABLES TO iclr_readonly;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ops.source_capability")
