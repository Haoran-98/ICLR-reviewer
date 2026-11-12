CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS semantic;
CREATE SCHEMA IF NOT EXISTS twin;

CREATE TABLE ops.schema_version (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    description TEXT NOT NULL
);
INSERT INTO ops.schema_version(version, description)
VALUES ('database_v1', 'Unified ICLR 2024-2026 main-track database')
ON CONFLICT (version) DO NOTHING;

CREATE TABLE raw.ingest_run (
    ingest_run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    code_version TEXT,
    source_root TEXT NOT NULL,
    inventory_path TEXT,
    statistics JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT
);

CREATE TABLE raw.source_record (
    source_record_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingest_run_id BIGINT NOT NULL REFERENCES raw.ingest_run,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('paper_metadata', 'openreview_snapshot')),
    source_path TEXT NOT NULL,
    conference_year SMALLINT NOT NULL CHECK (conference_year BETWEEN 2024 AND 2026),
    forum_id TEXT,
    sha256 CHAR(64) NOT NULL,
    byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
    fetched_at TIMESTAMPTZ,
    raw_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_path, sha256)
);
CREATE INDEX source_record_forum_idx ON raw.source_record(conference_year, forum_id);
CREATE INDEX source_record_payload_gin ON raw.source_record USING gin(raw_payload jsonb_path_ops);

CREATE TABLE raw.openreview_note (
    openreview_note_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_record_id BIGINT NOT NULL REFERENCES raw.source_record,
    note_id TEXT NOT NULL,
    forum_id TEXT NOT NULL,
    reply_to TEXT,
    invitation TEXT,
    signature TEXT,
    actor_role TEXT CHECK (actor_role IN ('author', 'reviewer', 'chair', 'unknown')),
    note_type TEXT NOT NULL CHECK (note_type IN ('official_review', 'author_response', 'reviewer_comment', 'decision', 'other')),
    created_ms BIGINT,
    modified_ms BIGINT,
    revision_no INTEGER NOT NULL DEFAULT 1 CHECK (revision_no > 0),
    content_hash CHAR(64) NOT NULL,
    raw_payload JSONB NOT NULL,
    UNIQUE (note_id, revision_no, content_hash)
);
CREATE INDEX openreview_note_forum_idx ON raw.openreview_note(forum_id, created_ms);
CREATE INDEX openreview_note_reply_idx ON raw.openreview_note(reply_to);

CREATE TABLE raw.openreview_edit (
    openreview_edit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    note_id TEXT NOT NULL,
    edit_id TEXT NOT NULL,
    forum_id TEXT,
    revision_no INTEGER NOT NULL CHECK (revision_no > 0),
    created_ms BIGINT,
    modified_ms BIGINT,
    content_hash CHAR(64) NOT NULL,
    raw_payload JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (edit_id, content_hash)
);
CREATE INDEX openreview_edit_note_idx ON raw.openreview_edit(note_id, revision_no);

CREATE TABLE raw.artifact (
    artifact_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingest_run_id BIGINT NOT NULL REFERENCES raw.ingest_run,
    source_path TEXT NOT NULL,
    object_path TEXT NOT NULL,
    sha256 CHAR(64) NOT NULL,
    extension TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
    source_type TEXT NOT NULL CHECK (source_type IN ('paper_json', 'openreview_json', 'pdf', 'markdown')),
    source_url TEXT,
    quality_status TEXT NOT NULL CHECK (quality_status IN ('available', 'missing', 'invalid')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_path, sha256)
);
CREATE INDEX raw_artifact_sha_idx ON raw.artifact(sha256);

CREATE TABLE raw.excluded_record (
    excluded_record_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingest_run_id BIGINT NOT NULL REFERENCES raw.ingest_run,
    source_path TEXT NOT NULL,
    conference_year SMALLINT,
    forum_id TEXT,
    reason TEXT NOT NULL,
    sha256 CHAR(64),
    UNIQUE (source_path, reason)
);

CREATE TABLE core.venue (
    venue_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    year SMALLINT NOT NULL CHECK (year BETWEEN 2024 AND 2026),
    track TEXT NOT NULL DEFAULT 'main',
    UNIQUE (name, year, track)
);

CREATE TABLE core.paper (
    paper_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue_id BIGINT NOT NULL REFERENCES core.venue,
    openreview_id TEXT NOT NULL,
    forum_id TEXT NOT NULL,
    openreview_url TEXT,
    pdf_url TEXT,
    status TEXT,
    track TEXT NOT NULL CHECK (track = 'main'),
    accepted_main BOOLEAN NOT NULL DEFAULT false,
    accepted_any BOOLEAN NOT NULL DEFAULT false,
    source_record_id BIGINT NOT NULL REFERENCES raw.source_record,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (venue_id, forum_id)
);
CREATE INDEX paper_openreview_idx ON core.paper(openreview_id);
CREATE INDEX paper_venue_status_idx ON core.paper(venue_id, accepted_main, status);

CREATE TABLE core.paper_version (
    paper_version_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    paper_id BIGINT NOT NULL REFERENCES core.paper ON DELETE CASCADE,
    version_no INTEGER NOT NULL CHECK (version_no > 0),
    title TEXT NOT NULL,
    abstract TEXT,
    tldr TEXT,
    keywords TEXT[] NOT NULL DEFAULT '{}',
    source_record_id BIGINT NOT NULL REFERENCES raw.source_record,
    content_hash CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ,
    modified_at TIMESTAMPTZ,
    UNIQUE (paper_id, content_hash)
);
CREATE INDEX paper_version_search_idx ON core.paper_version USING gin(
    to_tsvector('english', coalesce(title, '') || ' ' || coalesce(abstract, '') || ' ' || coalesce(tldr, ''))
);

CREATE TABLE core.author (
    author_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    identity_key TEXT NOT NULL UNIQUE,
    openreview_profile_id TEXT,
    name TEXT NOT NULL,
    orcid TEXT,
    profile JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE UNIQUE INDEX author_openreview_unique ON core.author(openreview_profile_id) WHERE openreview_profile_id IS NOT NULL;
CREATE UNIQUE INDEX author_name_without_profile_unique ON core.author(lower(name)) WHERE openreview_profile_id IS NULL;

CREATE TABLE core.affiliation (
    affiliation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    domain TEXT,
    UNIQUE NULLS NOT DISTINCT (name, domain)
);

CREATE TABLE core.paper_author (
    paper_id BIGINT NOT NULL REFERENCES core.paper ON DELETE CASCADE,
    author_id BIGINT NOT NULL REFERENCES core.author,
    author_position INTEGER NOT NULL CHECK (author_position > 0),
    PRIMARY KEY (paper_id, author_position),
    UNIQUE (paper_id, author_id)
);

CREATE TABLE core.author_affiliation (
    paper_id BIGINT NOT NULL REFERENCES core.paper ON DELETE CASCADE,
    author_id BIGINT NOT NULL REFERENCES core.author,
    affiliation_id BIGINT NOT NULL REFERENCES core.affiliation,
    PRIMARY KEY (paper_id, author_id, affiliation_id)
);

CREATE TABLE core.explicit_area (
    explicit_area_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    raw_label TEXT NOT NULL UNIQUE,
    canonical_key TEXT NOT NULL,
    first_year SMALLINT NOT NULL,
    last_year SMALLINT NOT NULL
);
CREATE INDEX explicit_area_canonical_idx ON core.explicit_area(canonical_key);

CREATE TABLE core.area_alias (
    raw_area_id BIGINT PRIMARY KEY REFERENCES core.explicit_area ON DELETE CASCADE,
    canonical_area_id BIGINT NOT NULL REFERENCES core.explicit_area,
    rationale TEXT NOT NULL
);

CREATE TABLE core.paper_area (
    paper_id BIGINT NOT NULL REFERENCES core.paper ON DELETE CASCADE,
    explicit_area_id BIGINT NOT NULL REFERENCES core.explicit_area,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    source_record_id BIGINT NOT NULL REFERENCES raw.source_record,
    PRIMARY KEY (paper_id, explicit_area_id)
);
CREATE INDEX paper_area_area_idx ON core.paper_area(explicit_area_id, paper_id);

CREATE TABLE core.artifact (
    paper_artifact_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    paper_id BIGINT NOT NULL REFERENCES core.paper ON DELETE CASCADE,
    raw_artifact_id BIGINT REFERENCES raw.artifact,
    artifact_role TEXT NOT NULL CHECK (artifact_role IN ('paper_json', 'openreview_json', 'pdf', 'markdown', 'supplement')),
    availability TEXT NOT NULL CHECK (availability IN ('available', 'missing', 'invalid')),
    quality_details JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (paper_id, artifact_role)
);

CREATE TABLE core.review (
    review_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    paper_id BIGINT NOT NULL REFERENCES core.paper ON DELETE CASCADE,
    source_note_id TEXT NOT NULL,
    reviewer_alias_hash CHAR(64) NOT NULL,
    raw_note_id BIGINT REFERENCES raw.openreview_note,
    created_at TIMESTAMPTZ,
    UNIQUE (paper_id, source_note_id)
);
CREATE INDEX review_paper_alias_idx ON core.review(paper_id, reviewer_alias_hash);

CREATE TABLE core.review_revision (
    review_revision_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    review_id BIGINT NOT NULL REFERENCES core.review ON DELETE CASCADE,
    revision_no INTEGER NOT NULL CHECK (revision_no > 0),
    summary TEXT,
    strengths TEXT,
    weaknesses TEXT,
    questions TEXT,
    ethics_concerns TEXT,
    raw_content JSONB NOT NULL,
    content_hash CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ,
    modified_at TIMESTAMPTZ,
    UNIQUE (review_id, content_hash),
    UNIQUE (review_id, revision_no)
);
CREATE INDEX review_revision_search_idx ON core.review_revision USING gin(
    to_tsvector('english', coalesce(summary, '') || ' ' || coalesce(strengths, '') || ' ' || coalesce(weaknesses, '') || ' ' || coalesce(questions, ''))
);

CREATE TABLE core.review_score (
    review_revision_id BIGINT PRIMARY KEY REFERENCES core.review_revision ON DELETE CASCADE,
    rating NUMERIC,
    confidence NUMERIC,
    soundness NUMERIC,
    contribution NUMERIC,
    presentation NUMERIC,
    raw_score JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE core.discussion_event (
    discussion_event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    paper_id BIGINT NOT NULL REFERENCES core.paper ON DELETE CASCADE,
    source_note_id TEXT NOT NULL,
    parent_note_id TEXT,
    parent_event_id BIGINT REFERENCES core.discussion_event,
    parent_review_id BIGINT REFERENCES core.review,
    raw_note_id BIGINT REFERENCES raw.openreview_note,
    actor_role TEXT NOT NULL CHECK (actor_role IN ('author', 'reviewer', 'chair', 'unknown')),
    event_type TEXT NOT NULL CHECK (event_type IN ('author_response', 'reviewer_response', 'public_comment', 'reminder', 'other')),
    signature TEXT,
    body TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ,
    modified_at TIMESTAMPTZ,
    raw_content JSONB NOT NULL,
    UNIQUE (paper_id, source_note_id)
);
CREATE INDEX discussion_paper_time_idx ON core.discussion_event(paper_id, created_at);
CREATE INDEX discussion_parent_idx ON core.discussion_event(parent_note_id);

CREATE TABLE core.decision (
    decision_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    paper_id BIGINT NOT NULL REFERENCES core.paper ON DELETE CASCADE,
    source_note_id TEXT,
    raw_decision TEXT,
    decision_category TEXT,
    accepted_main BOOLEAN NOT NULL,
    accepted_any BOOLEAN NOT NULL,
    source_record_id BIGINT NOT NULL REFERENCES raw.source_record,
    created_at TIMESTAMPTZ,
    UNIQUE (paper_id, source_record_id)
);

CREATE TABLE semantic.paper_profile (
    paper_profile_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    paper_id BIGINT NOT NULL REFERENCES core.paper ON DELETE CASCADE,
    profile_version TEXT NOT NULL,
    profile JSONB NOT NULL,
    confidence NUMERIC,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (paper_id, profile_version)
);

CREATE TABLE semantic.paper_fulltext_index (
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
CREATE INDEX paper_fulltext_status_idx
    ON semantic.paper_fulltext_index(status, deep_parse_status);

CREATE TABLE semantic.paper_content_object (
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
CREATE INDEX paper_content_object_lookup_idx
    ON semantic.paper_content_object(paper_id, object_type, deep_parse_status);

-- S4 extensions are applied by migration 0006; retain the 0001 bootstrap contract here.
CREATE TABLE semantic.taxonomy_node (
    taxonomy_node_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    taxonomy_version TEXT NOT NULL,
    level SMALLINT NOT NULL CHECK (level BETWEEN 1 AND 3),
    name TEXT NOT NULL,
    definition TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (taxonomy_version, level, name)
);

CREATE TABLE semantic.taxonomy_edge (
    parent_node_id BIGINT NOT NULL REFERENCES semantic.taxonomy_node ON DELETE CASCADE,
    child_node_id BIGINT NOT NULL REFERENCES semantic.taxonomy_node ON DELETE CASCADE,
    PRIMARY KEY (parent_node_id, child_node_id),
    CHECK (parent_node_id <> child_node_id)
);

CREATE TABLE semantic.paper_taxonomy_assignment (
    paper_id BIGINT NOT NULL REFERENCES core.paper ON DELETE CASCADE,
    taxonomy_node_id BIGINT NOT NULL REFERENCES semantic.taxonomy_node ON DELETE CASCADE,
    score NUMERIC NOT NULL CHECK (score BETWEEN 0 AND 1),
    source TEXT NOT NULL,
    PRIMARY KEY (paper_id, taxonomy_node_id, source)
);

CREATE TABLE semantic.embedding (
    embedding_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    paper_id BIGINT NOT NULL REFERENCES core.paper ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    content_hash CHAR(64) NOT NULL,
    embedding vector NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (paper_id, model_name, content_hash)
);

CREATE TABLE semantic.related_paper (
    source_paper_id BIGINT NOT NULL REFERENCES core.paper ON DELETE CASCADE,
    target_paper_id BIGINT NOT NULL REFERENCES core.paper ON DELETE CASCADE,
    method TEXT NOT NULL,
    score NUMERIC NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (source_paper_id, target_paper_id, method),
    CHECK (source_paper_id <> target_paper_id)
);

CREATE TABLE twin.expertise_archetype (
    expertise_archetype_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version TEXT NOT NULL,
    name TEXT NOT NULL,
    profile JSONB NOT NULL,
    UNIQUE (version, name)
);

CREATE TABLE twin.behavior_archetype (
    behavior_archetype_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version TEXT NOT NULL,
    name TEXT NOT NULL,
    profile JSONB NOT NULL,
    UNIQUE (version, name)
);

CREATE TABLE twin.reviewer_twin (
    reviewer_twin_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version TEXT NOT NULL,
    expertise_archetype_id BIGINT NOT NULL REFERENCES twin.expertise_archetype,
    behavior_archetype_id BIGINT NOT NULL REFERENCES twin.behavior_archetype,
    severity NUMERIC,
    rebuttal_parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (version, expertise_archetype_id, behavior_archetype_id)
);

CREATE TABLE twin.archetype_evidence (
    reviewer_twin_id BIGINT NOT NULL REFERENCES twin.reviewer_twin ON DELETE CASCADE,
    review_id BIGINT NOT NULL REFERENCES core.review ON DELETE CASCADE,
    weight NUMERIC NOT NULL DEFAULT 1,
    PRIMARY KEY (reviewer_twin_id, review_id)
);

CREATE TABLE twin.rebuttal_outcome (
    rebuttal_outcome_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    review_id BIGINT NOT NULL REFERENCES core.review ON DELETE CASCADE,
    discussion_event_id BIGINT REFERENCES core.discussion_event,
    resolution TEXT CHECK (resolution IN ('resolved', 'partially_resolved', 'unresolved', 'unknown')),
    score_action TEXT CHECK (score_action IN ('increased', 'maintained', 'decreased', 'promised_increase', 'unknown')),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE ops.pipeline_run (
    pipeline_run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_name TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    statistics JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT
);

CREATE TABLE ops.data_quality_issue (
    data_quality_issue_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingest_run_id BIGINT REFERENCES raw.ingest_run,
    paper_id BIGINT REFERENCES core.paper,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    entity_type TEXT,
    entity_key TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (paper_id, issue_type, entity_type, entity_key)
);

CREATE TABLE ops.dataset_snapshot (
    dataset_snapshot_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_read_only BOOLEAN NOT NULL DEFAULT true,
    table_counts JSONB NOT NULL,
    object_manifest_sha256 CHAR(64) NOT NULL,
    validation_report JSONB NOT NULL
);

CREATE VIEW core.latest_paper_version AS
SELECT DISTINCT ON (paper_id) *
FROM core.paper_version
ORDER BY paper_id, version_no DESC;

CREATE VIEW core.latest_review_revision AS
SELECT DISTINCT ON (review_id) *
FROM core.review_revision
ORDER BY review_id, revision_no DESC;

CREATE VIEW core.review_statistics AS
SELECT r.paper_id,
       count(s.rating) AS scored_reviews,
       avg(s.rating) AS average_rating,
       stddev_pop(s.rating) AS rating_stddev,
       min(s.rating) AS minimum_rating,
       max(s.rating) AS maximum_rating,
       avg(s.confidence) AS average_confidence
FROM core.review r
JOIN core.latest_review_revision rr USING (review_id)
LEFT JOIN core.review_score s USING (review_revision_id)
GROUP BY r.paper_id;

CREATE VIEW core.main_papers AS
SELECT p.*, v.year
FROM core.paper p
JOIN core.venue v USING (venue_id)
WHERE p.track = 'main';
