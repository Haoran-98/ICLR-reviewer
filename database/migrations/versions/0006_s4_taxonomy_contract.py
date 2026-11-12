"""Add the versioned S4 taxonomy contract.

Revision ID: 0006
Revises: 0005
"""
from alembic import op


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE semantic.taxonomy_version (
            taxonomy_version TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK (status IN ('experimental', 'candidate', 'frozen', 'retired')),
            profile_version TEXT NOT NULL,
            dataset_snapshot_id BIGINT REFERENCES ops.dataset_snapshot,
            split_manifest_hash CHAR(64) NOT NULL,
            config_hash CHAR(64) NOT NULL,
            code_commit TEXT,
            parent_version TEXT REFERENCES semantic.taxonomy_version,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            frozen_at TIMESTAMPTZ,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            CHECK (status <> 'frozen' OR frozen_at IS NOT NULL)
        );

        CREATE TABLE semantic.taxonomy_split (
            taxonomy_version TEXT NOT NULL REFERENCES semantic.taxonomy_version ON DELETE CASCADE,
            paper_id BIGINT NOT NULL REFERENCES core.paper ON DELETE CASCADE,
            split TEXT NOT NULL CHECK (split IN ('train', 'dev', 'calibration', 'test')),
            group_key TEXT NOT NULL,
            manifest_hash CHAR(64) NOT NULL,
            PRIMARY KEY (taxonomy_version, paper_id)
        );
        CREATE INDEX taxonomy_split_lookup_idx
            ON semantic.taxonomy_split(taxonomy_version, split, paper_id);

        CREATE TABLE semantic.embedding_spec (
            embedding_spec_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            spec_key TEXT NOT NULL UNIQUE,
            model_name TEXT NOT NULL,
            model_revision TEXT NOT NULL,
            representation_key TEXT NOT NULL,
            dimension INTEGER NOT NULL CHECK (dimension > 0),
            normalized BOOLEAN NOT NULL DEFAULT true,
            configuration JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        ALTER TABLE semantic.taxonomy_node
            ADD COLUMN stable_key TEXT,
            ADD COLUMN facet_type TEXT,
            ADD COLUMN valid_from_year SMALLINT,
            ADD COLUMN valid_to_year SMALLINT,
            ADD COLUMN inclusion_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN exclusion_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN review_status TEXT NOT NULL DEFAULT 'draft',
            ADD COLUMN provenance JSONB NOT NULL DEFAULT '{}'::jsonb;
        ALTER TABLE semantic.taxonomy_node
            ADD CONSTRAINT taxonomy_node_version_fk FOREIGN KEY (taxonomy_version)
                REFERENCES semantic.taxonomy_version ON DELETE CASCADE,
            ADD CONSTRAINT taxonomy_node_facet_check CHECK (
                facet_type IS NULL OR facet_type IN (
                    'task', 'method', 'application_domain', 'data_or_evidence',
                    'research_object', 'mixed', 'other'
                )
            ),
            ADD CONSTRAINT taxonomy_node_review_check CHECK (
                review_status IN ('draft', 'model_reviewed', 'accepted', 'rejected')
            ),
            ADD CONSTRAINT taxonomy_node_year_check CHECK (
                valid_from_year IS NULL OR valid_to_year IS NULL OR valid_from_year <= valid_to_year
            );
        CREATE UNIQUE INDEX taxonomy_node_stable_key_idx
            ON semantic.taxonomy_node(taxonomy_version, stable_key) WHERE stable_key IS NOT NULL;

        ALTER TABLE semantic.taxonomy_edge RENAME COLUMN parent_node_id TO source_node_id;
        ALTER TABLE semantic.taxonomy_edge RENAME COLUMN child_node_id TO target_node_id;
        ALTER TABLE semantic.taxonomy_edge DROP CONSTRAINT taxonomy_edge_pkey;
        ALTER TABLE semantic.taxonomy_edge
            ADD COLUMN taxonomy_version TEXT,
            ADD COLUMN relation_type TEXT NOT NULL DEFAULT 'parent_of',
            ADD COLUMN score NUMERIC NOT NULL DEFAULT 1 CHECK (score BETWEEN 0 AND 1),
            ADD COLUMN support_count INTEGER NOT NULL DEFAULT 0 CHECK (support_count >= 0),
            ADD COLUMN first_year SMALLINT,
            ADD COLUMN last_year SMALLINT,
            ADD COLUMN evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
            ADD CONSTRAINT taxonomy_edge_version_fk FOREIGN KEY (taxonomy_version)
                REFERENCES semantic.taxonomy_version ON DELETE CASCADE,
            ADD CONSTRAINT taxonomy_edge_type_check CHECK (relation_type IN (
                'parent_of', 'overlaps_with', 'method_used_in', 'application_of',
                'shares_evidence_pattern_with'
            )),
            ADD CONSTRAINT taxonomy_edge_year_check CHECK (
                first_year IS NULL OR last_year IS NULL OR first_year <= last_year
            );
        ALTER TABLE semantic.taxonomy_edge
            ADD PRIMARY KEY (taxonomy_version, source_node_id, target_node_id, relation_type);

        ALTER TABLE semantic.paper_taxonomy_assignment
            ADD COLUMN taxonomy_version TEXT,
            ADD COLUMN score_type TEXT NOT NULL DEFAULT 'similarity',
            ADD COLUMN rank INTEGER,
            ADD COLUMN is_primary BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN embedding_id BIGINT REFERENCES semantic.embedding,
            ADD COLUMN input_hash CHAR(64),
            ADD COLUMN calibration_version TEXT,
            ADD COLUMN evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
            ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            ADD CONSTRAINT paper_taxonomy_assignment_version_fk FOREIGN KEY (taxonomy_version)
                REFERENCES semantic.taxonomy_version ON DELETE CASCADE,
            ADD CONSTRAINT paper_taxonomy_assignment_score_type_check CHECK (
                score_type IN ('probability', 'similarity', 'conformal_pvalue', 'judge_proxy')
            ),
            ADD CONSTRAINT paper_taxonomy_assignment_rank_check CHECK (rank IS NULL OR rank > 0);
        CREATE INDEX paper_taxonomy_assignment_version_idx
            ON semantic.paper_taxonomy_assignment(taxonomy_version, paper_id, taxonomy_node_id);
        ALTER TABLE semantic.paper_taxonomy_assignment ALTER COLUMN taxonomy_version SET NOT NULL;

        ALTER TABLE semantic.embedding
            ADD COLUMN embedding_spec_id BIGINT REFERENCES semantic.embedding_spec,
            ADD COLUMN taxonomy_version TEXT REFERENCES semantic.taxonomy_version ON DELETE SET NULL,
            ADD COLUMN metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
        CREATE INDEX embedding_spec_lookup_idx
            ON semantic.embedding(embedding_spec_id, paper_id);

        CREATE TABLE semantic.taxonomy_judgment (
            taxonomy_judgment_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            taxonomy_version TEXT NOT NULL REFERENCES semantic.taxonomy_version ON DELETE CASCADE,
            entity_type TEXT NOT NULL CHECK (entity_type IN (
                'neighbor_pair', 'node', 'intruder', 'assignment', 'edge'
            )),
            entity_key TEXT NOT NULL,
            verdict TEXT NOT NULL,
            score NUMERIC CHECK (score BETWEEN 0 AND 1),
            model_name TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            input_hash CHAR(64) NOT NULL,
            response_hash CHAR(64) NOT NULL,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (taxonomy_version, entity_type, entity_key, prompt_version)
        );

        CREATE TABLE semantic.taxonomy_version_mapping (
            source_version TEXT NOT NULL REFERENCES semantic.taxonomy_version,
            source_node_id BIGINT NOT NULL REFERENCES semantic.taxonomy_node,
            target_version TEXT NOT NULL REFERENCES semantic.taxonomy_version,
            target_node_id BIGINT NOT NULL REFERENCES semantic.taxonomy_node,
            mapping_type TEXT NOT NULL CHECK (mapping_type IN ('same', 'rename', 'merge', 'split', 'retire')),
            score NUMERIC NOT NULL CHECK (score BETWEEN 0 AND 1),
            rationale TEXT NOT NULL,
            PRIMARY KEY (source_version, source_node_id, target_version, target_node_id, mapping_type)
        );

        CREATE OR REPLACE FUNCTION semantic.validate_taxonomy_edge() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE source_version TEXT; target_version TEXT; source_level SMALLINT; target_level SMALLINT;
        BEGIN
            SELECT taxonomy_version, level INTO source_version, source_level
            FROM semantic.taxonomy_node WHERE taxonomy_node_id = NEW.source_node_id;
            SELECT taxonomy_version, level INTO target_version, target_level
            FROM semantic.taxonomy_node WHERE taxonomy_node_id = NEW.target_node_id;
            IF source_version IS NULL OR source_version <> target_version OR source_version <> NEW.taxonomy_version THEN
                RAISE EXCEPTION 'taxonomy edge endpoints must belong to taxonomy version %', NEW.taxonomy_version;
            END IF;
            IF NEW.relation_type = 'parent_of' AND target_level <> source_level + 1 THEN
                RAISE EXCEPTION 'parent_of must connect adjacent levels';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER taxonomy_edge_validate
            BEFORE INSERT OR UPDATE ON semantic.taxonomy_edge
            FOR EACH ROW EXECUTE FUNCTION semantic.validate_taxonomy_edge();

        CREATE OR REPLACE FUNCTION semantic.validate_taxonomy_assignment() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE node_version TEXT;
        BEGIN
            SELECT taxonomy_version INTO node_version FROM semantic.taxonomy_node
            WHERE taxonomy_node_id = NEW.taxonomy_node_id;
            IF node_version IS NULL OR node_version <> NEW.taxonomy_version THEN
                RAISE EXCEPTION 'assignment node must belong to taxonomy version %', NEW.taxonomy_version;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER taxonomy_assignment_validate
            BEFORE INSERT OR UPDATE ON semantic.paper_taxonomy_assignment
            FOR EACH ROW EXECUTE FUNCTION semantic.validate_taxonomy_assignment();

        CREATE OR REPLACE FUNCTION semantic.validate_assignment_parent() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM semantic.paper_taxonomy_assignment a
                JOIN semantic.taxonomy_edge e ON e.target_node_id = a.taxonomy_node_id
                    AND e.taxonomy_version = a.taxonomy_version AND e.relation_type = 'parent_of'
                WHERE a.taxonomy_version = COALESCE(NEW.taxonomy_version, OLD.taxonomy_version)
                AND NOT EXISTS (SELECT 1 FROM semantic.paper_taxonomy_assignment pa
                    WHERE pa.paper_id = a.paper_id AND pa.taxonomy_node_id = e.source_node_id
                        AND pa.taxonomy_version = a.taxonomy_version)
            ) THEN RAISE EXCEPTION 'child assignment requires a parent assignment'; END IF;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER taxonomy_assignment_parent
            AFTER INSERT OR UPDATE OR DELETE ON semantic.paper_taxonomy_assignment
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION semantic.validate_assignment_parent();

        CREATE VIEW semantic.frozen_taxonomy_node AS
        SELECT n.* FROM semantic.taxonomy_node n
        JOIN semantic.taxonomy_version v USING (taxonomy_version)
        WHERE v.status = 'frozen';

        CREATE VIEW semantic.frozen_paper_taxonomy_assignment AS
        SELECT a.* FROM semantic.paper_taxonomy_assignment a
        JOIN semantic.taxonomy_version v USING (taxonomy_version)
        WHERE v.status = 'frozen';

        GRANT SELECT ON semantic.taxonomy_version, semantic.taxonomy_split,
            semantic.embedding_spec, semantic.taxonomy_judgment,
            semantic.taxonomy_version_mapping, semantic.frozen_taxonomy_node,
            semantic.frozen_paper_taxonomy_assignment
            TO iclr_readonly, iclr_app, iclr_ingest;
        GRANT INSERT, UPDATE, DELETE ON semantic.taxonomy_version, semantic.taxonomy_split,
            semantic.embedding_spec, semantic.taxonomy_judgment,
            semantic.taxonomy_version_mapping TO iclr_app;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA semantic TO iclr_app, iclr_ingest;
    """)


def downgrade() -> None:
    op.execute("""
        DROP VIEW IF EXISTS semantic.frozen_paper_taxonomy_assignment;
        DROP VIEW IF EXISTS semantic.frozen_taxonomy_node;
        DROP TRIGGER IF EXISTS taxonomy_assignment_parent ON semantic.paper_taxonomy_assignment;
        DROP FUNCTION IF EXISTS semantic.validate_assignment_parent();
        DROP TRIGGER IF EXISTS taxonomy_assignment_validate ON semantic.paper_taxonomy_assignment;
        DROP FUNCTION IF EXISTS semantic.validate_taxonomy_assignment();
        DROP TRIGGER IF EXISTS taxonomy_edge_validate ON semantic.taxonomy_edge;
        DROP FUNCTION IF EXISTS semantic.validate_taxonomy_edge();
        DROP TABLE IF EXISTS semantic.taxonomy_version_mapping;
        DROP TABLE IF EXISTS semantic.taxonomy_judgment;
        ALTER TABLE semantic.embedding DROP COLUMN IF EXISTS metadata;
        ALTER TABLE semantic.embedding DROP COLUMN IF EXISTS taxonomy_version;
        ALTER TABLE semantic.embedding DROP COLUMN IF EXISTS embedding_spec_id;
        DROP TABLE IF EXISTS semantic.embedding_spec;
        ALTER TABLE semantic.paper_taxonomy_assignment
            DROP COLUMN IF EXISTS created_at, DROP COLUMN IF EXISTS provenance,
            DROP COLUMN IF EXISTS evidence, DROP COLUMN IF EXISTS calibration_version,
            DROP COLUMN IF EXISTS input_hash, DROP COLUMN IF EXISTS embedding_id,
            DROP COLUMN IF EXISTS is_primary, DROP COLUMN IF EXISTS rank,
            DROP COLUMN IF EXISTS score_type, DROP COLUMN IF EXISTS taxonomy_version;
        ALTER TABLE semantic.taxonomy_edge DROP CONSTRAINT IF EXISTS taxonomy_edge_pkey;
        ALTER TABLE semantic.taxonomy_edge
            DROP COLUMN IF EXISTS provenance, DROP COLUMN IF EXISTS evidence,
            DROP COLUMN IF EXISTS last_year, DROP COLUMN IF EXISTS first_year,
            DROP COLUMN IF EXISTS support_count, DROP COLUMN IF EXISTS score,
            DROP COLUMN IF EXISTS relation_type, DROP COLUMN IF EXISTS taxonomy_version;
        ALTER TABLE semantic.taxonomy_edge ADD PRIMARY KEY (source_node_id, target_node_id);
        ALTER TABLE semantic.taxonomy_edge RENAME COLUMN source_node_id TO parent_node_id;
        ALTER TABLE semantic.taxonomy_edge RENAME COLUMN target_node_id TO child_node_id;
        DROP INDEX IF EXISTS semantic.taxonomy_node_stable_key_idx;
        ALTER TABLE semantic.taxonomy_node
            DROP COLUMN IF EXISTS provenance, DROP COLUMN IF EXISTS review_status,
            DROP COLUMN IF EXISTS exclusion_criteria, DROP COLUMN IF EXISTS inclusion_criteria,
            DROP COLUMN IF EXISTS valid_to_year, DROP COLUMN IF EXISTS valid_from_year,
            DROP COLUMN IF EXISTS facet_type, DROP COLUMN IF EXISTS stable_key;
        DROP TABLE IF EXISTS semantic.taxonomy_split;
        ALTER TABLE semantic.taxonomy_node DROP CONSTRAINT IF EXISTS taxonomy_node_version_fk;
        DROP TABLE IF EXISTS semantic.taxonomy_version;
    """)
