#!/usr/bin/env python3
"""Export completed paper profiles and a reproducible, local text-map baseline."""

import argparse
import csv
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


LATEST_REVIEWS = """
    SELECT DISTINCT ON (r.review_id)
        r.paper_id, r.review_id, rr.review_revision_id, rr.revision_no,
        rr.modified_at, s.rating, s.confidence, s.soundness,
        s.contribution, s.presentation,
        rr.raw_content ? '_openreview_edit' AS historical_edit
    FROM core.review r
    JOIN core.review_revision rr USING (review_id)
    LEFT JOIN core.review_score s USING (review_revision_id)
    ORDER BY r.review_id, rr.revision_no DESC, rr.review_revision_id DESC
"""


def project(papers):
    """Reuse a cached projection; never consume review scores or decisions as features."""
    import numpy as np
    import sklearn
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.decomposition import TruncatedSVD
    from sklearn.manifold import TSNE
    inputs = [(p["paper_id"], " ".join([p["title"] or "", p["summary"] or p["abstract"] or "",
              p["research_problem"] or "", p["method_overview"] or ""])) for p in papers]
    params = {"method": "TF-IDF → TruncatedSVD(64) → Barnes-Hut t-SNE", "seed": 42,
              "max_features": 40000, "ngram_range": [1, 2], "min_df": 2,
              "perplexity": min(40, len(papers) - 1), "max_iter": 750,
              "init": "pca", "learning_rate": "auto", "sklearn": sklearn.__version__}
    digest = hashlib.sha256(json.dumps([inputs, params], ensure_ascii=False).encode()).hexdigest()
    cache = Path(__file__).resolve().parents[1] / "logs/web_visualization/projections" / digest
    cache.mkdir(parents=True, exist_ok=True)
    if (cache / "projection.npz").exists():
        coords = np.load(cache / "projection.npz")["xy"]
    else:
        print("Computing TF-IDF/SVD/t-SNE for", len(papers), "papers", flush=True)
        matrix = TfidfVectorizer(max_features=40000, ngram_range=(1, 2), min_df=2,
                                 stop_words="english", sublinear_tf=True).fit_transform([t for _, t in inputs])
        vectors = TruncatedSVD(n_components=min(64, matrix.shape[1] - 1), random_state=42).fit_transform(matrix)
        # ponytail: existing sklearn provides a local baseline; no model download or paid API.
        coords = TSNE(n_components=2, perplexity=params["perplexity"], max_iter=750, init="pca",
                      learning_rate="auto", random_state=42, n_jobs=4, verbose=1).fit_transform(vectors)
        np.savez_compressed(cache / "projection.npz", xy=coords, vectors=vectors,
                            paper_ids=np.array([pid for pid, _ in inputs]))
        (cache / "metadata.json").write_text(json.dumps({**params, "input_sha256": digest}, indent=2))
    assert coords.shape == (len(papers), 2) and np.isfinite(coords).all()
    for paper, (x, y) in zip(papers, coords):
        paper.update(x=round(float(x), 5), y=round(float(y), 5))
    return {**params, "input_sha256": digest, "version": "tfidf-svd-tsne-" + digest[:16]}


def export(output, per_year):
    dsn = os.environ.get("ICLR_DATABASE_URL", "host=127.0.0.1 port=55432 dbname=iclr_reviewer")
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '120s'")
        snapshot = conn.execute("SELECT transaction_timestamp() AS at, txid_current_snapshot()::text AS tx_snapshot").fetchone()
        inventory = {}
        queries = {
            "counts": """SELECT
                (SELECT count(*) FROM core.paper) AS papers,
                (SELECT count(*) FROM core.paper_version) AS paper_versions,
                (SELECT count(*) FROM core.explicit_area) AS explicit_areas,
                (SELECT count(*) FROM core.review) AS reviews,
                (SELECT count(*) FROM core.review_revision) AS review_revisions,
                (SELECT count(*) FROM core.discussion_event) AS discussions,
                (SELECT count(*) FROM core.decision) AS decisions,
                (SELECT count(*) FROM semantic.embedding) AS embeddings,
                (SELECT count(*) FROM semantic.paper_taxonomy_assignment) AS taxonomy_assignments,
                (SELECT count(*) FROM raw.openreview_edit) AS edit_envelopes,
                (SELECT count(*) FROM raw.openreview_edit WHERE raw_payload #> '{note,content}' IS NOT NULL) AS edits_with_content,
                (SELECT count(*) FROM (SELECT review_id FROM core.review_revision GROUP BY review_id HAVING count(*)>1) q) AS reviews_with_multiple_versions""",
            "paper_coverage": """WITH pv AS (
                SELECT DISTINCT ON (paper_id) * FROM core.paper_version
                ORDER BY paper_id, version_no DESC, paper_version_id DESC)
                SELECT v.year, count(*) AS papers,
                    count(*) FILTER (WHERE nullif(trim(pv.title),'') IS NOT NULL) AS with_title,
                    count(*) FILTER (WHERE nullif(trim(pv.abstract),'') IS NOT NULL) AS with_abstract,
                    count(*) FILTER (WHERE cardinality(pv.keywords)>0) AS with_keywords,
                    count(*) FILTER (WHERE EXISTS(SELECT 1 FROM core.paper_area a WHERE a.paper_id=p.paper_id)) AS with_area
                FROM core.paper p JOIN core.venue v USING (venue_id)
                LEFT JOIN pv USING (paper_id) GROUP BY v.year ORDER BY v.year""",
            "review_coverage": f"""WITH latest AS ({LATEST_REVIEWS})
                SELECT v.year, count(*) AS reviews, count(l.rating) AS with_rating,
                    count(l.confidence) AS with_confidence, count(l.soundness) AS with_soundness,
                    count(l.contribution) AS with_contribution, count(l.presentation) AS with_presentation,
                    array_agg(DISTINCT l.rating ORDER BY l.rating) FILTER (WHERE l.rating IS NOT NULL) AS observed_ratings,
                    array_agg(DISTINCT l.confidence ORDER BY l.confidence) FILTER (WHERE l.confidence IS NOT NULL) AS observed_confidence
                FROM latest l JOIN core.paper p USING(paper_id) JOIN core.venue v USING(venue_id)
                GROUP BY v.year ORDER BY v.year""",
            "decision_coverage": """SELECT v.year,d.decision_category,count(*) AS papers
                FROM core.decision d JOIN core.paper p USING(paper_id) JOIN core.venue v USING(venue_id)
                GROUP BY v.year,d.decision_category ORDER BY v.year,d.decision_category""",
            "rating_labels": """SELECT v.year,s.rating,s.raw_score->>'rating' AS raw_rating,count(*) AS revisions
                FROM core.review_score s JOIN core.review_revision rr USING(review_revision_id)
                JOIN core.review r USING(review_id) JOIN core.paper p USING(paper_id)
                JOIN core.venue v USING(venue_id) GROUP BY 1,2,3 ORDER BY 1,2 NULLS LAST,4 DESC""",
        }
        for key, sql in queries.items():
            inventory[key] = conn.execute(sql).fetchall()
        papers = conn.execute("""
            WITH cohort AS (
                SELECT p.*,v.year,sp.paper_profile_id::text,sp.profile->>'summary' AS summary,
                    sp.profile #>> '{research_problem,statement}' AS research_problem,
                    sp.profile #>> '{method,overview}' AS method_overview,
                    coalesce((sp.provenance->>'needs_review')::boolean,false) AS needs_review
                FROM core.paper p JOIN core.venue v USING(venue_id)
                JOIN semantic.paper_profile sp USING(paper_id)
                WHERE sp.profile_version='paper_understanding_v1'), ranked AS (
                SELECT p.*,row_number() OVER (PARTITION BY p.year ORDER BY md5(p.forum_id),p.paper_id) AS rn
                FROM cohort p)
            SELECT p.paper_id::text,p.forum_id,p.year,p.openreview_url,
                p.paper_profile_id,p.summary,p.research_problem,p.method_overview,p.needs_review,
                pv.paper_version_id::text,pv.title,pv.abstract,pv.keywords,pv.content_hash,
                d.decision_category AS decision_raw,
                CASE WHEN d.decision_category IN ('Poster','Spotlight','Oral') THEN 'accepted'
                     WHEN d.decision_category='Reject' THEN 'rejected'
                     WHEN d.decision_category='Desk Reject' THEN 'desk_rejected'
                     WHEN d.decision_category='Withdraw' THEN 'withdrawn' ELSE 'unknown' END AS decision,
                coalesce((SELECT jsonb_agg(jsonb_build_object('area_id',a.explicit_area_id::text,
                    'label',a.raw_label,'canonical_key',a.canonical_key) ORDER BY a.explicit_area_id)
                    FROM core.paper_area pa JOIN core.explicit_area a USING(explicit_area_id)
                    WHERE pa.paper_id=p.paper_id),'[]'::jsonb) AS areas
            FROM ranked p
            LEFT JOIN LATERAL (SELECT * FROM core.paper_version pv WHERE pv.paper_id=p.paper_id
                ORDER BY version_no DESC,paper_version_id DESC LIMIT 1) pv ON true
            LEFT JOIN LATERAL (SELECT * FROM core.decision d WHERE d.paper_id=p.paper_id
                ORDER BY created_at DESC NULLS LAST,decision_id DESC LIMIT 1) d ON true
            WHERE (%s::integer IS NULL OR rn<=%s) ORDER BY year,rn
        """, (per_year, per_year)).fetchall()
        ids = [int(p["paper_id"]) for p in papers]
        reviews = conn.execute(f"""WITH latest AS ({LATEST_REVIEWS})
            SELECT l.paper_id::text,l.review_id::text,l.review_revision_id::text,
                l.revision_no,l.rating::float8,l.confidence::float8,l.soundness::float8,
                l.contribution::float8,l.presentation::float8,l.historical_edit,v.year
            FROM latest l JOIN core.paper p USING(paper_id) JOIN core.venue v USING(venue_id)
            WHERE l.paper_id=ANY(%s) ORDER BY v.year,l.paper_id,l.review_id""", (ids,)).fetchall()
    projection = project(papers)
    by_paper = defaultdict(list)
    for review in reviews:
        by_paper[review["paper_id"]].append(review)
    edges = {}
    for index, paper in enumerate(papers):
        ratings = [r["rating"] for r in by_paper[paper["paper_id"]] if r["rating"] is not None]
        paper.update(review_count=len(by_paper[paper["paper_id"]]), rating_count=len(ratings),
                     mean_rating=sum(ratings) / len(ratings) if ratings else None)
        for area in paper["areas"]:
            key = "area:" + area["area_id"]
            edge = edges.setdefault(key, {"edge_id": key, "type": "explicit_area", "label": area["label"],
                                          "source": "core.paper_area", "paper_ids": []})
            edge["paper_ids"].append(paper["paper_id"])
    digest = hashlib.sha256(json.dumps([papers, reviews, projection], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    totals = {"papers": len(papers), "reviews": len(reviews),
              "valid_ratings": sum(r["rating"] is not None for r in reviews),
              "needs_review": sum(p["needs_review"] for p in papers)}
    meta = {
        "contract_version": "v2-baseline", "data_version": "processed-" + digest[:16],
        "content_sha256": digest, "extracted_at": snapshot["at"].isoformat(),
        "transaction_snapshot": snapshot["tx_snapshot"],
        "paper_version_policy": "max_version_no_then_paper_version_id",
        "review_version_policy": "latest_observed_revision_no_then_revision_id",
        "profile_version": "paper_understanding_v1", "projection": projection,
        "projection_version": projection["version"], "semantic_projection": False,
        "sample_method": "all_completed_profiles" if per_year is None else "completed_profiles_per_year_md5",
        "per_year": per_year, "totals": totals,
        "details_base": "details-" + digest[:16],
    }
    ids_set = {p["paper_id"] for p in papers}
    assert len(ids_set) == len(papers)
    assert len({r["review_id"] for r in reviews}) == len(reviews)
    assert all(r["paper_id"] in ids_set for r in reviews)
    output.mkdir(parents=True, exist_ok=True)
    details_dir = output / meta["details_base"]
    details_dir.mkdir(exist_ok=True)
    chunks = defaultdict(dict)
    heavy = ["abstract", "summary", "research_problem", "method_overview", "areas", "keywords",
             "content_hash", "paper_profile_id", "paper_version_id", "openreview_url"]
    for index, paper in enumerate(papers):
        chunk = str(index // 200)
        detail = {key: paper.pop(key) for key in heavy}
        detail["reviews"] = by_paper[paper["paper_id"]]
        chunks[chunk][paper["paper_id"]] = detail
        paper["detail_chunk"] = chunk
    for chunk, details in chunks.items():
        (details_dir / (chunk + ".json")).write_text(json.dumps(details, ensure_ascii=False, separators=(",", ":")))
    (output / "hyperedges.json").write_text(json.dumps(list(edges.values()), ensure_ascii=False, separators=(",", ":")))
    payload = {"papers": papers, "meta": meta}
    temp = output / "sample.json.tmp"
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    temp.replace(output / "sample.json")
    inventory["meta"] = meta
    (output / "inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2, default=str) + "\n")
    with (output / "reviews.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["paper_id", "review_id", "year", "rating", "confidence"])
        writer.writeheader()
        writer.writerows({k: r[k] for k in writer.fieldnames} for r in reviews)
    print(json.dumps({**totals, "hyperedges": len(edges), **meta}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "public/generated")
    parser.add_argument("--per-year", type=int, default=None)
    args = parser.parse_args()
    if args.per_year is not None and not 1 <= args.per_year <= 100:
        parser.error("--per-year must be between 1 and 100")
    export(args.output, args.per_year)
