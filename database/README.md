# Unified ICLR Database

This directory builds the PostgreSQL 16 + pgvector data layer for the ICLR
2024-2026 main-track corpus, including source records, full-text indexes,
version history, and artifact provenance.

## Storage

- PostgreSQL data: `/data_big/iclr-reviewer-db/postgres`
- Content-addressed files: `/data_big/iclr-reviewer-store/objects`
- Inventories and reports: `/data_big/iclr-reviewer-db/state`
- Read-only snapshot: `/data_big/iclr-reviewer-db/snapshots/database_v1.dump.zst`

The original `/data_big/iclr_reviews` tree is never modified. Object-store
entries are hard links when source and target are on the same filesystem.

## Build

```bash
python -m pip install -r requirements.txt
bash database/bootstrap_postgres.sh
export ICLR_DATABASE_URL=postgresql://$USER@127.0.0.1:55432/iclr_reviewer
python database/iclr_database.py all
```

The installed user service keeps only PostgreSQL running after login/reboot:

```bash
systemctl --user status iclr-reviewer-postgres.service
```

Individual resumable stages are `inventory`, `object-store`, `migrate`,
`ingest`, `fulltext-index`, `revision-audit`, `revision-backfill`, `validate`, and `snapshot`. The `all` command performs a second
ingest and rejects any business-table count change as an idempotency failure.

## Text-first full-text index

The initial full-text pass reads existing Markdown and stores lightweight
retrieval metadata in PostgreSQL. Complete text stays in the object store.
Deep parsing can be requested separately for selected objects.

Run it after migration and core ingestion:

```bash
python database/iclr_database.py migrate
python database/iclr_database.py fulltext-index
```

The command is resumable and idempotent. It compares the content-addressed
source artifact and `index_version`; unchanged papers are skipped without
opening the Markdown file.

The index is stored in two PostgreSQL tables:

- `semantic.paper_fulltext_index`: one row per paper. It stores the source
  artifact foreign key, content hash, status, character/token/page counts,
  headings, object counts, routing signals, and `deep_parse_status`.
- `semantic.paper_content_object`: one row per unique numbered figure, table,
  equation, theorem, or algorithm in a paper. It stores the label, caption,
  approximate page, character offsets, occurrence count, confidence, and
  on-demand parse status.

The original Markdown remains in the content-addressed object store and is
reached through `core.artifact -> raw.artifact`. PostgreSQL stores the map and
provenance.

Inspect coverage:

```sql
SELECT status, count(*)
FROM semantic.paper_fulltext_index
GROUP BY status;

SELECT object_type, count(*)
FROM semantic.paper_content_object
GROUP BY object_type;
```

Retrieve one paper and its indexed objects:

```sql
SELECT p.forum_id, v.year, f.status, f.headings,
       f.object_counts, f.routing_signals, f.deep_parse_status
FROM core.paper p
JOIN core.venue v USING (venue_id)
JOIN semantic.paper_fulltext_index f USING (paper_id)
WHERE p.forum_id = 'OPENREVIEW_FORUM_ID';

SELECT object_type, object_key, label, caption, page_number,
       char_start, char_end, occurrence_count, deep_parse_status
FROM semantic.paper_content_object
WHERE paper_id = (
    SELECT paper_id FROM core.paper
    WHERE forum_id = 'OPENREVIEW_FORUM_ID'
)
ORDER BY page_number, char_start;
```

PostgreSQL data lives under `/data_big/iclr-reviewer-db/postgres`. Access it
through SQL or the Python database API; do not edit PostgreSQL's binary files.

`revision-audit` probes deterministic Review notes through the authenticated
OpenReview edits API and records whether replayable historical content is
actually public. Migration-only edit envelopes are stored but are not treated
as reconstructed historical revisions. Each run checkpoints both empty and
non-empty responses, so rerunning it advances to the next notes instead of
repeating completed requests. Full revision backfill remains bounded by the
OpenReview account rate limit.

`revision-backfill` uses conference-domain pagination and filters Review edits
locally, reducing the full history import from one request per Review to about
one request per 1,000 conference edits. It checkpoints every page in
`revision_backfill_checkpoint.json` and is safe to resume.

OpenReview access uses a seven-day session token. API reads use only the token
stored with mode `0600` at `/data_big/iclr_reviews/fulltext/openreview.token`.
Issue or renew it through TOTP MFA:

```bash
python scripts/get_openreview_token.py
```

The TOTP setup secret is read from the ignored repository-local `auth` file.
Background jobs never read that file or retry account authentication; they
stop with an explicit renewal message one hour before token expiry.

Store either `OPENREVIEW_TOTP_SECRET="Base32 setup secret"` or the full
`otpauth://...` URI. `KEY` remains accepted as a compatibility alias. The
OpenReview username and password come from the same file when present, then
fall back to `/home/yhr/auth`. The script computes the six-digit code locally
and never prints it.

For a one-time code entered directly in the terminal, run:

```bash
python scripts/get_openreview_token_with_code.py
```

It selects TOTP when OpenReview offers it, otherwise email OTP, and asks for
the code only after the login challenge has started. OpenReview's MFA verify
endpoint currently rejects custom expiry values, so code-based login produces
the server default one-day token even though the client requests seven days.

## Access

```bash
/data_big/iclr-reviewer-db/runtime/bin/psql \
  postgresql://$USER@127.0.0.1:55432/iclr_reviewer
```

Restore the snapshot with:

```bash
zstd -dc /data_big/iclr-reviewer-db/snapshots/database_v1.dump.zst > /tmp/database_v1.dump
/data_big/iclr-reviewer-db/runtime/bin/pg_restore --dbname TARGET_DATABASE /tmp/database_v1.dump
```
