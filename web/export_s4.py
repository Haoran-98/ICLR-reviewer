#!/usr/bin/env python3
"""Publish the sealed S4 cohort, observed decisions/reviews and source-backed entity labels."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path('/data_big/iclr-s4/experiments/entity_core_third_gpt6luna_medium_dual_v1')


def project_s4(papers, root):
    import numpy as np
    import sklearn
    from sklearn.decomposition import PCA
    from sklearn.manifold import TSNE
    metadata = json.loads((root / "embeddings/metadata.json").read_text())["core"]["bge-m3"]
    vector_file = root / metadata["path"]
    assert hashlib.sha256(vector_file.read_bytes()).hexdigest() == metadata["file_sha256"]
    stored = np.load(vector_file)
    print("S4 vector columns:", stored.files, flush=True)
    id_key = next(key for key in ["paper_ids", "ids"] if key in stored)
    vector_key = next(key for key in ["vectors", "embeddings"] if key in stored)
    by_id = {str(pid): index for index, pid in enumerate(stored[id_key])}
    vectors = stored[vector_key][[by_id[p["paper_id"]] for p in papers]]
    params = {"method": "S4 BGE-M3 core embeddings → PCA(50) → Barnes-Hut t-SNE", "seed": 42,
              "perplexity": 40, "max_iter": 750, "init": "pca", "learning_rate": "auto",
              "sklearn": sklearn.__version__, "embedding": metadata}
    digest = hashlib.sha256(json.dumps([params, [p["paper_id"] for p in papers]], sort_keys=True).encode()).hexdigest()
    cache = Path(__file__).resolve().parents[1] / "logs/web_visualization/projections" / digest
    cache.mkdir(parents=True, exist_ok=True)
    if (cache / "projection.npz").exists():
        coords = np.load(cache / "projection.npz")["xy"]
    else:
        reduced = PCA(n_components=50, random_state=42).fit_transform(vectors)
        coords = TSNE(n_components=2, perplexity=40, max_iter=750, init="pca", learning_rate="auto",
                      random_state=42, n_jobs=4, verbose=1).fit_transform(reduced)
        np.savez_compressed(cache / "projection.npz", xy=coords, paper_ids=[p["paper_id"] for p in papers])
        (cache / "metadata.json").write_text(json.dumps(params, indent=2))
    assert len(coords) == len(papers) and np.isfinite(coords).all()
    for p, (x, y) in zip(papers, coords): p.update(x=round(float(x), 5), y=round(float(y), 5))
    return {**params, "version": "s4-bge-core-tsne-" + digest[:16], "input_sha256": digest}


def export(output, root):
    gold = json.loads((root / 'evaluation/gold.json').read_text())
    ids = [int(row['paper_id']) for row in gold]
    gold_by_id = {str(row['paper_id']): row for row in gold}
    seal_hash = hashlib.sha256((root / 'SEALED.json').read_bytes()).hexdigest()
    with psycopg.connect(os.environ.get('ICLR_DATABASE_URL', 'host=127.0.0.1 port=55432 dbname=iclr_reviewer'), row_factory=dict_row) as conn:
        conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        snapshot = conn.execute('SELECT transaction_timestamp() AS at, txid_current_snapshot()::text AS tx_snapshot').fetchone()
        # Scalar columns suffice: do not read unrelated raw JSON or reprocess S3 profiles.
        papers = conn.execute('''SELECT p.paper_id::text,p.forum_id,v.year,d.decision_category AS decision_raw,
            CASE WHEN d.decision_category IN ('Poster','Spotlight','Oral') THEN 'accepted'
                 WHEN d.decision_category='Reject' THEN 'rejected'
                 WHEN d.decision_category='Desk Reject' THEN 'desk_rejected'
                 WHEN d.decision_category='Withdraw' THEN 'withdrawn' ELSE 'unknown' END AS decision
            FROM core.paper p JOIN core.venue v USING(venue_id)
            LEFT JOIN LATERAL (SELECT decision_category FROM core.decision d WHERE d.paper_id=p.paper_id
                ORDER BY created_at DESC NULLS LAST,decision_id DESC LIMIT 1) d ON true
            WHERE p.paper_id=ANY(%s) ORDER BY v.year,p.paper_id''', (ids,)).fetchall()
        reviews = conn.execute('''SELECT DISTINCT ON (r.review_id) r.paper_id::text,r.review_id::text,
            rr.review_revision_id::text,rr.revision_no,s.rating::float8,s.confidence::float8,v.year
            FROM core.review r JOIN core.review_revision rr USING(review_id)
            LEFT JOIN core.review_score s USING(review_revision_id)
            JOIN core.paper p USING(paper_id) JOIN core.venue v USING(venue_id)
            WHERE r.paper_id=ANY(%s) ORDER BY r.review_id,rr.revision_no DESC,rr.review_revision_id DESC''', (ids,)).fetchall()
    assert {int(p['paper_id']) for p in papers} == set(ids)
    by_paper = defaultdict(list)
    for review in reviews: by_paper[review['paper_id']].append(review)
    sources, entities, per_paper = {}, {}, {}
    input_hash = hashlib.sha256()
    for p in papers:
        raw = (root / 'papers' / (p['paper_id'] + '.json')).read_bytes()
        input_hash.update(raw)
        source = json.loads(raw); sources[p['paper_id']] = source
        core = source['core']
        p.update(title=source['title'], summary=source['core_text'], abstract=source['abstract'],
                 research_problem=core['research_problem']['text'], method_overview=core['method']['text'],
                 needs_review=False, domain=gold_by_id[p['paper_id']]['area'])
        ratings = [r['rating'] for r in by_paper[p['paper_id']] if r['rating'] is not None]
        p.update(review_count=len(by_paper[p['paper_id']]), rating_count=len(ratings),
                 mean_rating=sum(ratings)/len(ratings) if ratings else None)
        memberships = set()
        for candidate in source['entity_candidates']:
            if not candidate['literal_span_valid'] or candidate['salience'] != 'core': continue
            key = (candidate['entity_type'], candidate['normalized_key'])
            entities.setdefault(key, {'label': candidate['mention_text'], 'type': candidate['entity_type'], 'normalized': candidate['normalized_key']})
            memberships.add(key)
        per_paper[p['paper_id']] = (memberships, ratings)
    projection = project_s4(papers, root)
    sorted_keys = sorted(entities); entity_ids = {key: i for i,key in enumerate(sorted_keys)}
    source_hash = input_hash.hexdigest()
    digest = hashlib.sha256(json.dumps([papers, reviews, source_hash, projection], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    details_base, evidence_base = 'details-' + digest[:16], 's4-evidence-' + source_hash[:16]
    output.mkdir(parents=True, exist_ok=True)
    (output / details_base).mkdir(exist_ok=True); (output / evidence_base).mkdir(exist_ok=True)
    chunks = defaultdict(dict); analysis_rows = []
    for index,p in enumerate(papers):
        pid = p['paper_id']; source = sources[pid]; p['detail_chunk'] = str(index//100)
        detail = {key:p.pop(key) for key in ['summary','abstract','research_problem','method_overview']}
        detail.update(reviews=by_paper[pid], keywords=source['original_labels']['keywords'],
                      areas=[{'label':source['original_labels']['primary_area'],'canonical_key':p['domain']}],
                      s4_evidence=f'{evidence_base}/{pid}.json')
        chunks[p['detail_chunk']][pid] = detail
        # Preserve original fields, candidate IDs, literal validity and character offsets in lazy evidence files.
        (output / evidence_base / (pid + '.json')).write_text(json.dumps(source,ensure_ascii=False,separators=(',',':')))
        member_keys,ratings = per_paper[pid]
        analysis_rows.append({'paper_id':pid,'domain':p['domain'],'entities':sorted(entity_ids[k] for k in member_keys),'ratings':ratings})
    for chunk, rows in chunks.items():
        (output / details_base / (chunk+'.json')).write_text(json.dumps(rows,ensure_ascii=False,separators=(',',':')))
    totals = {'papers':len(papers),'reviews':len(reviews),'valid_ratings':sum(p['rating_count'] for p in papers),'needs_review':0}
    meta = {'contract_version':'s4-entities-v1','data_version':'s4-'+digest[:16],'content_sha256':digest,
            'extracted_at':snapshot['at'].isoformat(),'transaction_snapshot':snapshot['tx_snapshot'],
            'details_base':details_base,'evidence_base':evidence_base,'totals':totals,
            's4_source':root.name,'s4_seal_sha256':seal_hash,'s4_papers_sha256':source_hash,
            'paper_version_policy':'sealed_S4_title_abstract_core','review_version_policy':'latest_observed_revision_no_then_revision_id',
            'projection_version':projection['version'],'projection':projection,'semantic_projection':True,'sample_method':'sealed_S4_12964'}
    domain_keys = sorted({p['domain'] for p in papers})
    from field_labels import LABELS
    analysis = {'meta':{'source_data_version':meta['data_version'],'label_source':root.name,
                       'label_policy':'literal_span_valid=true AND salience=core; one membership per entity_type+normalized_key per paper',
                       'chord_weight':'unique papers containing both S4 entity labels; no self chords'},
                'domains':[{'id':key,'label':LABELS.get(key,key),'raw_labels':sorted({row['raw_label'] for row in gold if row['area']==key})} for key in domain_keys],
                'entities':[{'id':entity_ids[key],**entities[key]} for key in sorted_keys],
                'papers':analysis_rows,'evidence_base':evidence_base}
    (output / 'domains.json').write_text(json.dumps(analysis,ensure_ascii=False,separators=(',',':')))
    with (output / 'reviews.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['paper_id','review_id','year','rating','confidence']);writer.writeheader()
        writer.writerows({key:r[key] for key in writer.fieldnames} for r in reviews)
    temporary=output/'sample.json.tmp';temporary.write_text(json.dumps({'papers':papers,'meta':meta},ensure_ascii=False,separators=(',',':')));temporary.replace(output/'sample.json')
    from derive_topics import derive
    derive(output)
    assert len(reviews)==len({r['review_id'] for r in reviews})
    assert sum(len(row['ratings']) for row in analysis_rows)==totals['valid_ratings']
    print(json.dumps({**totals,'entities':len(sorted_keys),'by_year':dict(Counter(p['year'] for p in papers)),**meta},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--output',type=Path,default=Path(__file__).parent/'public/generated');args=parser.parse_args();export(args.output,args.root)
