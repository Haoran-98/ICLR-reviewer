"""Add text-first full-text indexing with on-demand deep parsing.

Revision ID: 0005
Revises: 0004
"""
from alembic import op


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS semantic.paper_fulltext_index (
            paper_id BIGINT PRIMARY KEY REFERENCES core.paper ON DELETE CASCADE,
            source_artifact_id BIGINT REFERENCES core.artifact ON DELETE SET NULL,
            index_version TEXT NOT NULL,
            content_hash CHAR(64),
            status TEXT NOT NULL CHECK (status IN ('indexed', 'missing', 'invalid')),
            processing_policy TEXT NOT NULL DEFAULT 'text_first_on_demand',
            deep_parse_status TEXT NOT NULL DEFAULT 'not_requested'
                CHECK (deep_parse_status IN ('not_requested', 'requested', 'running', 'complete', 'failed')),
            char_count INTEGER NOT NULL DEFAULT 0,
            token_count INTEGER NOT NULL DEFAULT 0,
            page_count INTEGER,
            headings JSONB NOT NULL DEFAULT '[]'::jsonb,
            object_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
            routing_signals JSONB NOT NULL DEFAULT '{}'::jsonb,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS paper_fulltext_status_idx
            ON semantic.paper_fulltext_index(status, deep_parse_status);

        CREATE TABLE IF NOT EXISTS semantic.paper_content_object (
            content_object_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            paper_id BIGINT NOT NULL REFERENCES core.paper ON DELETE CASCADE,
            object_type TEXT NOT NULL
                CHECK (object_type IN ('figure', 'table', 'equation', 'theorem', 'algorithm')),
            object_key TEXT NOT NULL,
            label TEXT,
            caption TEXT,
            page_number INTEGER,
            char_start INTEGER NOT NULL,
            char_end INTEGER NOT NULL,
            occurrence_count INTEGER NOT NULL DEFAULT 1 CHECK (occurrence_count > 0),
            extraction_method TEXT NOT NULL DEFAULT 'lightweight_regex_v1',
            confidence NUMERIC NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            deep_parse_status TEXT NOT NULL DEFAULT 'not_requested'
                CHECK (deep_parse_status IN ('not_requested', 'requested', 'running', 'complete', 'failed')),
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            UNIQUE (paper_id, object_type, object_key)
        );
        CREATE INDEX IF NOT EXISTS paper_content_object_lookup_idx
            ON semantic.paper_content_object(paper_id, object_type, deep_parse_status);

        GRANT SELECT ON semantic.paper_fulltext_index, semantic.paper_content_object
            TO iclr_readonly, iclr_app, iclr_ingest;
        GRANT INSERT, UPDATE, DELETE ON semantic.paper_fulltext_index, semantic.paper_content_object
            TO iclr_app, iclr_ingest;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA semantic TO iclr_app, iclr_ingest;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS semantic.paper_content_object;
        DROP TABLE IF EXISTS semantic.paper_fulltext_index;
    """)
