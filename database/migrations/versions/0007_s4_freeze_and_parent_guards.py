"""Protect frozen S4 artifacts and bound parent validation to the affected paper.

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision='0007'
down_revision='0006'
branch_labels=None
depends_on=None


def upgrade():
    op.execute("""
        CREATE OR REPLACE FUNCTION semantic.validate_assignment_parent() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE version_key TEXT; paper_key BIGINT;
        BEGIN
            version_key := COALESCE(NEW.taxonomy_version, OLD.taxonomy_version);
            paper_key := COALESCE(NEW.paper_id, OLD.paper_id);
            IF EXISTS (
                SELECT 1 FROM semantic.paper_taxonomy_assignment a
                JOIN semantic.taxonomy_node n USING (taxonomy_node_id)
                WHERE a.taxonomy_version = version_key AND a.paper_id = paper_key AND n.level > 1
                  AND (NOT EXISTS (SELECT 1 FROM semantic.taxonomy_edge e
                        WHERE e.target_node_id=a.taxonomy_node_id AND e.relation_type='parent_of')
                    OR EXISTS (SELECT 1 FROM semantic.taxonomy_edge e
                        WHERE e.target_node_id=a.taxonomy_node_id AND e.relation_type='parent_of'
                        AND NOT EXISTS (SELECT 1 FROM semantic.paper_taxonomy_assignment p
                            WHERE p.paper_id=paper_key AND p.taxonomy_node_id=e.source_node_id
                                AND p.taxonomy_version=version_key)))
            ) THEN RAISE EXCEPTION 'child assignment requires a parent assignment'; END IF;
            RETURN NULL;
        END $$;

        CREATE FUNCTION semantic.protect_frozen_taxonomy() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE version_key TEXT;
        BEGIN
            version_key := COALESCE(NEW.taxonomy_version, OLD.taxonomy_version);
            IF EXISTS (SELECT 1 FROM semantic.taxonomy_version
                       WHERE taxonomy_version=version_key AND status IN ('frozen','retired')) THEN
                RAISE EXCEPTION 'frozen/retired taxonomy artifacts are immutable';
            END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER frozen_node_guard BEFORE INSERT OR UPDATE OR DELETE ON semantic.taxonomy_node
            FOR EACH ROW EXECUTE FUNCTION semantic.protect_frozen_taxonomy();
        CREATE TRIGGER frozen_edge_guard BEFORE INSERT OR UPDATE OR DELETE ON semantic.taxonomy_edge
            FOR EACH ROW EXECUTE FUNCTION semantic.protect_frozen_taxonomy();
        CREATE TRIGGER frozen_assignment_guard BEFORE INSERT OR UPDATE OR DELETE ON semantic.paper_taxonomy_assignment
            FOR EACH ROW EXECUTE FUNCTION semantic.protect_frozen_taxonomy();
        CREATE TRIGGER frozen_split_guard BEFORE INSERT OR UPDATE OR DELETE ON semantic.taxonomy_split
            FOR EACH ROW EXECUTE FUNCTION semantic.protect_frozen_taxonomy();

        CREATE FUNCTION semantic.protect_taxonomy_version() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='DELETE' THEN
                IF OLD.status IN ('frozen','retired') THEN RAISE EXCEPTION 'cannot delete a frozen version'; END IF;
                RETURN OLD;
            END IF;
            IF TG_OP='UPDATE' AND OLD.status IN ('frozen','retired') THEN
                IF (to_jsonb(NEW)-'status') <> (to_jsonb(OLD)-'status')
                  OR NEW.status NOT IN ('frozen','retired')
                  OR (OLD.status='retired' AND NEW.status <> 'retired') THEN
                    RAISE EXCEPTION 'frozen version metadata is immutable; only retirement is allowed';
                END IF;
            END IF;
            IF NEW.status='frozen' AND (
                NEW.taxonomy_version LIKE 'taxonomy_smoke%%'
                OR COALESCE(NEW.metadata->>'s3_frozen','false') <> 'true'
                OR NEW.dataset_snapshot_id IS NULL
            ) THEN RAISE EXCEPTION 'freeze requires a real S3 snapshot; smoke cannot freeze'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER taxonomy_version_guard BEFORE INSERT OR UPDATE OR DELETE ON semantic.taxonomy_version
            FOR EACH ROW EXECUTE FUNCTION semantic.protect_taxonomy_version();
    """)


def downgrade():
    op.execute("""
        DROP TRIGGER IF EXISTS taxonomy_version_guard ON semantic.taxonomy_version;
        DROP FUNCTION IF EXISTS semantic.protect_taxonomy_version();
        DROP TRIGGER IF EXISTS frozen_node_guard ON semantic.taxonomy_node;
        DROP TRIGGER IF EXISTS frozen_edge_guard ON semantic.taxonomy_edge;
        DROP TRIGGER IF EXISTS frozen_assignment_guard ON semantic.paper_taxonomy_assignment;
        DROP TRIGGER IF EXISTS frozen_split_guard ON semantic.taxonomy_split;
        DROP FUNCTION IF EXISTS semantic.protect_frozen_taxonomy();
    """)
    # 0006's version-level validation remains functionally equivalent on valid data.
