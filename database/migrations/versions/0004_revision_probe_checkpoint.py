"""Checkpoint OpenReview revision probes.

Revision ID: 0004
Revises: 0003
"""
from alembic import op


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE raw.openreview_revision_probe (
            note_id TEXT PRIMARY KEY,
            checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
            edit_count INTEGER NOT NULL DEFAULT 0,
            content_edit_count INTEGER NOT NULL DEFAULT 0,
            error TEXT
        );
        INSERT INTO raw.openreview_revision_probe(note_id, status, edit_count, content_edit_count)
        SELECT note_id, 'success', count(*),
               count(*) FILTER (WHERE raw_payload #> '{note,content}' IS NOT NULL)
        FROM raw.openreview_edit
        GROUP BY note_id;
        GRANT SELECT ON raw.openreview_revision_probe TO iclr_readonly, iclr_app, iclr_ingest;
        GRANT INSERT, UPDATE, DELETE ON raw.openreview_revision_probe TO iclr_ingest;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS raw.openreview_revision_probe")
