#!/usr/bin/env python3
"""Recover only excess counts of otherwise valid source citations, without inference."""
import argparse
from copy import deepcopy
from pathlib import Path

import jsonschema
import re
import modular_review_skill as s


def recover(root):
    recovered=[]
    for folder in sorted((root/'requests/extract').iterdir()):
        if (folder/'result.json').exists():continue
        attempts=sorted(folder.glob('attempt_*.json'))
        if not attempts:continue
        original=s.read(attempts[-1]);raw=original.get('response',{})
        if original.get('ok') or not original.get('finished_at') or raw.get('status')!='completed':continue
        if raw.get('model')!=s.MODEL or raw.get('reasoning',{}).get('effort')!='medium':continue
        request=s.read(folder/'request.json');payload=s.json.loads(request['body']['input'])
        schema=payload['schema']
        try:parsed=s.response_json(raw)
        except (ValueError,KeyError):continue
        errors=list(jsonschema.Draft202012Validator(schema).iter_errors(parsed))
        def citation_count_only(error):
            path=list(error.absolute_path)
            return (error.validator=='maxItems' and len(path)==3 and path[0]=='cases'
                    and isinstance(path[1],int) and path[2] in ['paper_evidence_ids','review_evidence_ids']
                    and len(error.instance)<=8)
        if not errors or not all(citation_count_only(e) for e in errors):continue
        relaxed=deepcopy(schema)
        for field in ['paper_evidence_ids','review_evidence_ids']:
            relaxed['properties']['cases']['items']['properties'][field]['maxItems']=8
        jsonschema.validate(parsed,relaxed);s.validate_extraction(parsed)
        record=dict(original,ok=True,parsed=parsed,recovered_without_inference=True,
            recovery=dict(policy='Preserve all model citations. Relax only source-case citation count from 3 to 8; '
                'keep every enum, required field and all other schema constraints unchanged.',
                original_attempt=attempts[-1].name,original_error=original.get('error'),
                changed_paths=[list(e.absolute_path) for e in errors],
                original_schema_hash=s.digest(schema),recovery_schema_hash=s.digest(relaxed)))
        s.write(folder/'recovery.json',record)
        s.write(folder/'result.json',record)
        recovered.append(folder.name)
    return recovered


def recover_reviews(root):
    """Canonicalize only a unique numeric shorthand for an actual target passage."""
    recovered=[]
    for folder in sorted((root/'requests/review').glob('*')):
        if (folder/'result.json').exists():continue
        attempts=sorted(folder.glob('attempt_*.json'))
        if not attempts:continue
        original=s.read(attempts[-1]);raw=original.get('response',{})
        if not original.get('finished_at') or raw.get('status')!='completed':continue
        if raw.get('model')!=s.MODEL or raw.get('reasoning',{}).get('effort')!='medium':continue
        request=s.read(folder/'request.json');payload=s.json.loads(request['body']['input'])
        passages=payload['data']['manuscript']['paper_passages']
        supplied={p['passage_id'] for p in passages}
        parsed=s.response_json(raw);fixed=deepcopy(parsed);mappings=[];valid=True
        for field in ['strengths','concerns']:
            for index,item in enumerate(fixed[field]):
                for n,eid in enumerate(item['evidence_ids']):
                    if eid in supplied:continue
                    match=re.fullmatch(r'T([0-9]{4})',eid)
                    options=[p for p in supplied if match and p==f'T{parsed["paper_id"]}:P{match.group(1)}']
                    if len(options)!=1:valid=False;continue
                    item['evidence_ids'][n]=options[0]
                    mappings.append(dict(path=[field,index,'evidence_ids',n],original=eid,canonical=options[0]))
        if not valid or not mappings:continue
        try:jsonschema.validate(fixed,payload['schema'])
        except jsonschema.ValidationError:continue
        record=dict(original,ok=True,parsed=fixed,recovered_without_inference=True,
            recovery=dict(policy='Canonicalize a unique Tdddd shorthand to the supplied target passage T<paper>:Pdddd. '
                'No evidence is added and the original schema remains unchanged.',kind='unique_target_alias',
                mappings=mappings,original_attempt=attempts[-1].name,original_error=original.get('error'),
                schema_hash=s.digest(payload['schema'])))
        s.write(folder/'recovery.json',record);s.write(folder/'result.json',record)
        recovered.append(folder.name)
    return recovered


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=s.ROOT)
    args=parser.parse_args()
    print(s.json.dumps(dict(recovered=recover(args.root),target_aliases=recover_reviews(args.root),inference_calls=0),ensure_ascii=False))
