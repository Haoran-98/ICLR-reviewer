"""Close frozen-artifact update and parent-edge deletion loopholes.

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE OR REPLACE FUNCTION semantic.protect_frozen_taxonomy() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM semantic.taxonomy_version
                WHERE taxonomy_version IN (OLD.taxonomy_version, NEW.taxonomy_version)
                    AND status IN ('frozen','retired')) THEN
                RAISE EXCEPTION 'frozen/retired taxonomy artifacts are immutable';
            END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER frozen_embedding_guard BEFORE INSERT OR UPDATE OR DELETE ON semantic.embedding
            FOR EACH ROW EXECUTE FUNCTION semantic.protect_frozen_taxonomy();
        CREATE TRIGGER frozen_judgment_guard BEFORE INSERT OR UPDATE OR DELETE ON semantic.taxonomy_judgment
            FOR EACH ROW EXECUTE FUNCTION semantic.protect_frozen_taxonomy();

        CREATE FUNCTION semantic.protect_frozen_embedding_spec() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (TG_OP='DELETE' OR NEW IS DISTINCT FROM OLD) AND EXISTS (
                SELECT 1 FROM semantic.embedding e JOIN semantic.taxonomy_version v USING(taxonomy_version)
                WHERE e.embedding_spec_id=OLD.embedding_spec_id AND v.status IN ('frozen','retired')
            ) THEN RAISE EXCEPTION 'frozen embedding specification is immutable'; END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER frozen_embedding_spec_guard BEFORE UPDATE OR DELETE ON semantic.embedding_spec
            FOR EACH ROW EXECUTE FUNCTION semantic.protect_frozen_embedding_spec();

        CREATE OR REPLACE FUNCTION semantic.validate_assignment_parent() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM semantic.paper_taxonomy_assignment a
                JOIN semantic.taxonomy_node n USING(taxonomy_node_id)
                WHERE (a.taxonomy_version,a.paper_id) IN (
                    (OLD.taxonomy_version,OLD.paper_id),(NEW.taxonomy_version,NEW.paper_id))
                  AND n.level>1 AND (
                    NOT EXISTS (SELECT 1 FROM semantic.taxonomy_edge e
                        WHERE e.target_node_id=a.taxonomy_node_id AND e.relation_type='parent_of')
                    OR EXISTS (SELECT 1 FROM semantic.taxonomy_edge e
                        WHERE e.target_node_id=a.taxonomy_node_id AND e.relation_type='parent_of'
                          AND NOT EXISTS (SELECT 1 FROM semantic.paper_taxonomy_assignment p
                            WHERE p.paper_id=a.paper_id AND p.taxonomy_node_id=e.source_node_id
                              AND p.taxonomy_version=a.taxonomy_version)))
            ) THEN RAISE EXCEPTION 'child assignment requires a parent assignment'; END IF;
            RETURN NULL;
        END $$;

        CREATE FUNCTION semantic.validate_edge_assignments() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM semantic.paper_taxonomy_assignment a
                JOIN semantic.taxonomy_node n USING(taxonomy_node_id)
                WHERE a.taxonomy_node_id IN (OLD.target_node_id,NEW.target_node_id)
                  AND n.level>1 AND (
                    NOT EXISTS (SELECT 1 FROM semantic.taxonomy_edge e
                        WHERE e.target_node_id=a.taxonomy_node_id AND e.relation_type='parent_of')
                    OR EXISTS (SELECT 1 FROM semantic.taxonomy_edge e
                        WHERE e.target_node_id=a.taxonomy_node_id AND e.relation_type='parent_of'
                          AND NOT EXISTS (SELECT 1 FROM semantic.paper_taxonomy_assignment p
                            WHERE p.paper_id=a.paper_id AND p.taxonomy_node_id=e.source_node_id
                              AND p.taxonomy_version=a.taxonomy_version)))
            ) THEN RAISE EXCEPTION 'parent edge change invalidates child assignments'; END IF;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER taxonomy_edge_assignment_guard
            AFTER INSERT OR UPDATE OR DELETE ON semantic.taxonomy_edge
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION semantic.validate_edge_assignments();
    """)


def downgrade():
    op.execute("""
        DROP TRIGGER taxonomy_edge_assignment_guard ON semantic.taxonomy_edge;
        DROP FUNCTION semantic.validate_edge_assignments();
        DROP TRIGGER frozen_embedding_spec_guard ON semantic.embedding_spec;
        DROP FUNCTION semantic.protect_frozen_embedding_spec();
        DROP TRIGGER frozen_embedding_guard ON semantic.embedding;
        DROP TRIGGER frozen_judgment_guard ON semantic.taxonomy_judgment;
    """)
    # The existing 0007 trigger functions retain stricter, compatible checks.
