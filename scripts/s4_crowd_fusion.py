#!/usr/bin/env python3
"""Auditable post-generation stages for S4 v4; no fine-grained gold labels."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import time

import numpy as np
import psycopg
from psycopg.types.json import Jsonb
from sklearn.decomposition import PCA
from sklearn.metrics import f1_score
from sklearn.model_selection import GroupKFold

import s4_llm_taxonomy as s4
import s4_kimi_batch as kimi_batch


PAPER_REPRESENTATIONS = {
    'title_abstract': ('title','abstract'),
    'title_abstract_keywords': ('title','abstract','keywords'),
}


def providers(args):
    return tuple(getattr(args,'providers',None) or
                 s4.read(args.root/'manifest.json',{}).get('providers',s4.PROVIDERS))


def source_root(args):
    source = s4.read(args.root/'manifest.json',{}).get('source_root')
    return Path(source) if source else None


def replacements(args):
    root=getattr(args,'root',None)
    return s4.read(root/'manifest.json',{}).get('role_replacement',{}) if root else {}


def replacement_value(value, role, actual, model=None):
    value=copy.deepcopy(value)
    for vote in value.get('votes',[]):
        vote.update(assigned_role=role,actual_provider=actual,
                    replacement_policy='retain_history_replace_only_missing_work')
        if model:
            vote['actual_model']=model
    return value


def independent_votes(entries):
    """A replacement's repeated GPT observation has one effective vote."""
    result={}
    for role,vote in entries.items():
        actual=vote.get('actual_provider',role)
        if actual not in result or role==actual:
            result[actual]=vote
    return result


def scope_approved(entries):
    unique=independent_votes(entries)
    return (sum(v['vote']=='yes' for v in unique.values())>=len(unique)//2+1
            and not any(v['vote']=='no' for v in unique.values()))


def prepare_branch(args):
    source = getattr(args,'source_root',None)
    if source is None:
        return
    source = source.resolve()
    if source == args.root.resolve():
        raise ValueError('Analysis branch must have a separate output directory')
    selected = providers(args)
    original = s4.read(source/'manifest.json')
    manifest = {**original,'version':args.root.name,'parent_version':original['version'],
        'source_root':str(source),'providers':list(selected),'created_at':s4.now(),
        'excluded_providers':[p for p in s4.PROVIDERS if p not in selected],
        'role_replacement':{'kimi':'openai'} if getattr(args,'replace_kimi_with_openai',False) else {},
        'replacement_policy':'reuse gpt-6-luna results; a model contributes one vote, not two',
        'paper_representations':PAPER_REPRESENTATIONS,
        'reuse_policy':'original full candidate-set cross-votes filtered to retained candidate IDs'}
    existing = s4.read(args.root/'manifest.json')
    if existing:
        if any(existing.get(k) != manifest[k] for k in ('source_root','providers','version','role_replacement')):
            raise ValueError('Existing branch has a different source/provider configuration')
        return
    args.root.mkdir(parents=True,exist_ok=True)
    # Share immutable inputs and the request ledger, preserving every original retry budget.
    for name in ('raw','sections','generated','official_votes','section_vectors.npz',
                 'embedding_stats.json','section_stats.json','chunks.json','chunk_vectors.npy',
                 'jobs','results','attempts'):
        target = args.root/name
        if not target.exists():
            target.symlink_to(source/name)
    if selected==tuple(s4.PROVIDERS):
        # All historical candidates/definitions are retained, so these immutable inputs match.
        for name in ('label_vectors.npz','alignment_pairs.json'):
            if (source/name).exists() and not (args.root/name).exists():
                (args.root/name).symlink_to(source/name)
    if (source/'local_server.json').exists():
        s4.write(args.root/'local_server.json',s4.read(source/'local_server.json'))
    s4.write(args.root/'manifest.json',manifest)
    s4.log('analysis_branch_prepared',root=str(args.root),providers=selected,source_root=str(source))


def normalized(text):
    return re.sub(r'[^a-z0-9]+',' ',text.casefold()).strip()


def canonicalize(args):
    path=args.root/'canonical.json'
    if path.exists():
        return s4.read(path)
    nodes={}
    raw=[]
    for paper in s4.read(args.root/'manifest.json')['papers']:
        pid=paper['paper_id']
        for provider in providers(args):
            generated=s4.read(args.root/'generated'/provider/f'{pid}.json')
            local={}
            for level in (1,2,3):
                for node in generated[str(level)]:
                    if node['status']!='candidate':
                        continue
                    cid=s4.digest([level,normalized(node['name']),node['facet']])[:24]
                    rid=s4.digest([pid,provider,level,node['node_id']])
                    parent=local.get((level-1,node.get('parent_id')))
                    if level>1 and not parent:
                        continue
                    local[(level,node['node_id'])]=cid
                    if cid not in nodes:
                        nodes[cid]={**node,'id':cid,'members':[],'parents':[]}
                    nodes[cid]['members'].append({'paper_id':pid,'provider':provider,'raw_id':rid,
                                                 'evidence':node['supporting_quotes']})
                    if parent and parent not in nodes[cid]['parents']:
                        nodes[cid]['parents'].append(parent)
                    raw.append({'raw_id':rid,'paper_id':pid,'provider':provider,'level':level,
                                'local_id':node['node_id'],'canonical_id':cid,'parent_id':parent})
    result={'nodes':nodes,'raw_mapping':raw,'providers':list(providers(args)),
            'alignment_policy':'level/name/facet exact lexical normalization; semantic merges require independent votes'}
    s4.write(path,result)
    s4.log('canonicalized',nodes=len(nodes),raw_candidates=len(raw))
    return result


def label_embed(args):
    if (args.root/'label_vectors.npz').exists():
        return
    import torch
    from sentence_transformers import SentenceTransformer
    nodes=canonicalize(args)['nodes']
    ids=sorted(nodes)
    torch.set_num_threads(8)
    model=SentenceTransformer(str(s4.MODEL_PATH),device='cuda',local_files_only=True,
                             model_kwargs={'torch_dtype':torch.float16,'use_safetensors':False})
    model.max_seq_length=512
    vectors=model.encode([nodes[i]['name']+'\n'+nodes[i]['definition'] for i in ids],
                         batch_size=8,normalize_embeddings=True,show_progress_bar=True).astype('float32')
    np.savez_compressed(args.root/'label_vectors.npz',ids=np.array(ids),vectors=vectors)


def representation_text(sections, fields):
    return '\n\n'.join(field+':\n'+sections[field]['text'] for field in fields
                       if not sections[field]['missing'])


def paper_embed(args):
    if (args.root/'paper_representations.npz').exists():
        return
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(8)
    model=SentenceTransformer(str(s4.MODEL_PATH),device='cuda',local_files_only=True,
                             model_kwargs={'torch_dtype':torch.float16,'use_safetensors':False})
    model.max_seq_length=512
    ids=[p['paper_id'] for p in s4.read(args.root/'manifest.json')['papers']]
    chunks=[]
    records=[]
    audit=[]
    for pid in ids:
        sections=s4.read(args.root/'sections'/f'{pid}.json')
        for name,fields in PAPER_REPRESENTATIONS.items():
            text=representation_text(sections,fields)
            tokens=model.tokenizer.encode(text,add_special_tokens=False)
            audit.append({'paper_id':pid,'representation':name,'fields':fields,
                'input_hash':s4.digest(text),'token_count':len(tokens),
                'missing_fields':[field for field in fields if sections[field]['missing']],
                'section_hashes':{field:sections[field]['content_hash'] for field in fields}})
            for start in range(0,len(tokens),446):
                chunks.append(model.tokenizer.decode(tokens[start:start+510],skip_special_tokens=True))
                records.append({'paper_id':pid,'representation':name,'token_start':start,
                                'token_end':min(start+510,len(tokens))})
                if start+510>=len(tokens):
                    break
    encoded=model.encode(chunks,batch_size=8,normalize_embeddings=True,
                         show_progress_bar=True).astype('float32')
    grouped=defaultdict(list)
    for i,item in enumerate(records):
        grouped[(item['paper_id'],item['representation'])].append(i)
    output={'paper_ids':np.array(ids)}
    for name in PAPER_REPRESENTATIONS:
        vectors=np.zeros((len(ids),encoded.shape[1]),dtype='float32')
        for i,pid in enumerate(ids):
            members=grouped[(pid,name)]
            if members:
                mean=encoded[members].mean(0)
                vectors[i]=mean/max(np.linalg.norm(mean),1e-12)
        output[name]=vectors
    s4.write(args.root/'representation_inputs.json',audit)
    s4.write(args.root/'representation_chunks.json',records)
    s4.write(args.root/'paper_representation_spec.json',{'model':'BAAI/bge-m3','revision':s4.REVISION,
        'fields':PAPER_REPRESENTATIONS,'layout':'field name followed by original text; fields joined with two newlines',
        'chunk_tokens':512,'content_tokens':510,'overlap':64,'pooling':'normalized_mean_of_normalized_chunks',
        'comparison_scope':'paper embedding inputs only; label embeddings and LLM evidence unchanged'})
    np.savez_compressed(args.root/'paper_representations.npz',**output)
    s4.log('paper_representations_complete',papers=len(ids),representations=list(PAPER_REPRESENTATIONS))


def embed_analysis(args):
    label_embed(args)
    paper_embed(args)


def semantic_pairs(args):
    cached=s4.read(args.root/'alignment_pairs.json')
    if cached is not None:
        return cached
    from sklearn.neighbors import NearestNeighbors
    canonical=canonicalize(args)
    data=np.load(args.root/'label_vectors.npz')
    ids=data['ids'].tolist()
    vectors=data['vectors']
    result=[]
    for level in (1,2,3):
        selected=[i for i,cid in enumerate(ids) if canonical['nodes'][cid]['level']==level]
        if len(selected)<2:
            continue
        subset=vectors[selected]
        nearest=NearestNeighbors(n_neighbors=min(3,len(subset)),metric='cosine').fit(subset)
        distances,indices=nearest.kneighbors(subset)
        seen=set()
        for i,neighbors in enumerate(indices):
            for position,j in enumerate(neighbors):
                if i==j or distances[i,position]>.12:
                    continue
                a,b=sorted((ids[selected[i]],ids[selected[j]]))
                if (a,b) not in seen:
                    seen.add((a,b))
                    result.append({'id':s4.digest([a,b]),'a':a,'b':b,'cosine':float(1-distances[i,position])})
                break
    s4.write(args.root/'alignment_pairs.json',result)
    return result


def parallel_providers(args,callback):
    config=s4.credentials(args.auth)
    routing=replacements(args)
    with ThreadPoolExecutor(max_workers=len(providers(args))) as executor:
        futures=[executor.submit(callback,p,config[p]['concurrency']) for p in providers(args) if p not in routing]
        for future in futures:
            future.result()
    # Original GPT jobs finish first, so a replacement can reuse their exact cache IDs.
    for role,actual in routing.items():
        if role in providers(args):
            callback(role,config[actual]['concurrency'])


def evaluate_batches(args, provider, kind, payloads, workers):
    actual=replacements(args).get(provider)
    if actual:
        configs=s4.credentials(args.auth)
        config=configs[provider]
        def request(payload):
            historical,_=s4.build_job(config,provider,kind,payload)
            cached=s4.read(args.root/'results'/f'{historical["job_id"]}.json')
            if cached:
                return cached['value']
            return replacement_value(s4.request_job(args,actual,kind,payload),provider,actual,configs[actual]['model'])
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures=[executor.submit(request,payload) for payload in payloads]
            return [future.result() for future in futures]
    if provider == 'kimi':
        return kimi_batch.request_many(args, kind, payloads)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(s4.request_job,args,provider,kind,payload) for payload in payloads]
        return [future.result() for future in futures]


def align(args):
    if (args.root/'alignment_votes.json').exists():
        return s4.read(args.root/'alignment_votes.json')
    nodes=canonicalize(args)['nodes']
    pairs=semantic_pairs(args)
    votes={}
    source=source_root(args)
    old_nodes=s4.read(source/'canonical.json',{}).get('nodes',{}) if source else {}
    old_votes=s4.read(source/'alignment_votes.json',{}) if source else {}
    compatible={pair['id'] for pair in pairs if all(
        cid in old_nodes and all(nodes[cid][k]==old_nodes[cid][k] for k in ('name','definition','facet'))
        for cid in (pair['a'],pair['b']))}
    def one_provider(provider,workers):
        retained=[v for v in old_votes.get(provider,[]) if v['id'] in compatible]
        seen={v['id'] for v in retained}
        pending=[pair for pair in pairs if pair['id'] not in seen]
        payloads=[]
        for start in range(0,len(pending),32):
            batch=pending[start:start+32]
            items=[{'id':pair['id'],'a':{k:nodes[pair['a']][k] for k in ('name','definition','facet')},
                   'b':{k:nodes[pair['b']][k] for k in ('name','definition','facet')}} for pair in batch]
            payloads.append({'instruction':
                'For each pair decide whether the two domain definitions are equivalent and safe to merge. '
                'Related or overlapping is NOT equivalent. Return {votes:[{id,vote:yes/no/abstain,rationale}]}.',
                'items':items})
        votes[provider]=retained+[v for value in evaluate_batches(args,provider,'align',payloads,workers) for v in value['votes']]
    parallel_providers(args,one_provider)
    s4.write(args.root/'alignment_votes.json',votes)
    return votes


def crosslabel(args):
    canonical=canonicalize(args)
    by_paper=defaultdict(set)
    for row in canonical['raw_mapping']:
        by_paper[row['paper_id']].add(row['canonical_id'])
    source=source_root(args)
    if source:
        routing=replacements(args)
        while True:
            missing=[(p,pid) for p in providers(args) if p not in routing for pid in by_paper
                     if not (source/'crosslabels'/p/f'{pid}.json').exists()]
            s4.write(args.root/'source_crosslabel_progress.json',{'updated_at':s4.now(),
                'source_root':str(source),'providers':list(providers(args)),
                'missing_papers_by_provider':dict(Counter(p for p,pid in missing))})
            if not missing:
                break
            state=s4.read(source/'postprocess_execution.json',{})
            if state.get('status')=='failed':
                raise RuntimeError('Source cross-votes incomplete; see source_crosslabel_progress.json')
            time.sleep(30)
        old_nodes=s4.read(source/'canonical.json')['nodes']
        compatible={cid for cid,node in canonical['nodes'].items() if cid in old_nodes and all(
            node[k]==old_nodes[cid][k] for k in ('name','definition','level','facet'))}
        def reuse_provider(provider,workers):
            payloads=[]
            task_pids=[]
            retained={}
            for pid,ids in by_paper.items():
                original=s4.read(source/'crosslabels'/provider/f'{pid}.json')
                if original is None and provider in routing:
                    original=replacement_value({'votes':s4.read(source/'crosslabels'/routing[provider]/f'{pid}.json')},
                        provider,routing[provider],s4.credentials(args.auth)[routing[provider]]['model'])['votes']
                if not ids <= {v['id'] for v in original}:
                    raise ValueError('Source cross-votes do not cover retained candidate IDs')
                retained[pid]=[vote for vote in original if vote['id'] in ids & compatible]
                changed=sorted(ids-compatible)
                for start in range(0,len(changed),32):
                    payloads.append(crosslabel_payload(args,pid,canonical['nodes'],changed[start:start+32]))
                    task_pids.append(pid)
            values=evaluate_batches(args,provider,'crosslabel',payloads,workers) if payloads else []
            for pid,value in zip(task_pids,values):
                retained[pid].extend(validate_crossvotes(args,pid,value))
            for pid,values in retained.items():
                s4.write(args.root/'crosslabels'/provider/f'{pid}.json',values)
        parallel_providers(args,reuse_provider)
        s4.write(args.root/'crosslabel_complete.json',{'papers':len(by_paper),
            'providers':list(providers(args)),'source_root':str(source),'created_at':s4.now()})
        return
    def one_provider(provider,workers):
        tasks=[]
        for pid in sorted(by_paper):
            target=args.root/'crosslabels'/provider/f'{pid}.json'
            if target.exists():
                continue
            ids=sorted(by_paper[pid])
            for start in range(0,len(ids),32):
                tasks.append((pid,crosslabel_payload(args,pid,canonical['nodes'],ids[start:start+32])))
        values=evaluate_batches(args,provider,'crosslabel',[payload for _,payload in tasks],workers)
        by_result=defaultdict(list)
        for (pid,_),value in zip(tasks,values):
            by_result[pid].extend(validate_crossvotes(args,pid,value))
        for pid,results in by_result.items():
            s4.write(args.root/'crosslabels'/provider/f'{pid}.json',results)
    parallel_providers(args,one_provider)
    s4.write(args.root/'crosslabel_complete.json',{'papers':len(by_paper),'created_at':s4.now()})


def crosslabel_payload(args,pid,nodes,ids):
    return {'instruction':
        'Independently judge whether THIS paper belongs to each proposed domain. '
        'Use yes for supported own research, no for contradicted scope, abstain for insufficient evidence. '
        'Related work alone cannot prove this paper belongs to a field. '
        'Return {votes:[{id,vote:yes/no/abstain,evidence_refs:[],rationale}]}.',
        'items':[{'id':cid,**{k:nodes[cid][k] for k in ('name','definition','level','facet')}} for cid in ids],
        'evidence':s4.evidence_packet(args,pid)}


def validate_crossvotes(args,pid,value):
    evidence={s['span_id']:s for s in s4.evidence_packet(args,pid)}
    for vote in value['votes']:
        refs=vote.get('evidence_refs',[])
        if not isinstance(refs,list) or not all(isinstance(ref,str) for ref in refs):
            refs=[]
        if vote['vote']=='yes' and (not refs or not all(ref in evidence for ref in refs)
            or not any(evidence[ref]['section_id']!='related_work' for ref in refs if ref in evidence)):
            vote.update(original_vote='yes',vote='abstain',rejection_reason='invalid_own_contribution_evidence')
        vote['supporting_quotes']=[evidence[ref] for ref in refs if ref in evidence]
    return value['votes']


def validate_hierarchy(args):
    target=args.root/'hierarchy_votes.json'
    if target.exists():
        return
    nodes=canonicalize(args)['nodes']
    items=[]
    for cid,node in nodes.items():
        for parent in node['parents']:
            items.append({'id':s4.digest([parent,cid]),'parent_id':parent,'child_id':cid,
                          'parent':{k:nodes[parent][k] for k in ('name','definition','facet')},
                          'child':{k:node[k] for k in ('name','definition','facet')}})
    votes={}
    def one_provider(provider,workers):
        payloads=[{'instruction':
                'For each proposed parent/child pair, decide if the complete child scope is contained '
                'in the parent scope. Similarity, shared datasets or methods USED IN a domain are insufficient. '
                'Vote yes/no/abstain. Return {votes:[{id,vote,rationale}]}.','items':items[i:i+32]}
                for i in range(0,len(items),32)]
        votes[provider]=[vote for value in evaluate_batches(args,provider,'align',payloads,workers) for vote in value['votes']]
    parallel_providers(args,one_provider)
    s4.write(target,{'edges':items,'votes':votes})


def majority(votes):
    observed=votes>=0
    count=observed.sum(1)
    return np.divide((votes==1).sum(1),count,out=np.full(len(votes),.5),where=count>0)


def dawid_skene(votes,iterations=100):
    """Binary DS with missing labels masked, Dirichlet(1) smoothing."""
    q=np.clip(majority(votes),.05,.95)
    confusion=np.zeros((votes.shape[1],2,2))
    for _ in range(iterations):
        weights=np.column_stack((1-q,q))
        for j in range(votes.shape[1]):
            for truth in (0,1):
                counts=np.array([1+weights[votes[:,j]==label,truth].sum() for label in (0,1)])
                confusion[j,truth]=counts/counts.sum()
        prior=np.clip(weights.mean(0),.01,.99)
        likelihood=np.tile(np.log(prior),(len(votes),1))
        for j in range(votes.shape[1]):
            for label in (0,1):
                likelihood[votes[:,j]==label]+=np.log(np.maximum(confusion[j,:,label],1e-8))
        likelihood-=likelihood.max(1,keepdims=True)
        posterior=np.exp(likelihood)
        posterior/=posterior.sum(1,keepdims=True)
        new=posterior[:,1]
        if np.max(abs(new-q))<1e-6:
            q=new
            break
        q=new
    return q,confusion


def masked_views(base,votes,classes):
    """Predicting annotator j never sees j's own vote in its feature view."""
    result=[]
    for held in range(votes.shape[1]):
        encoded=np.zeros((len(votes),votes.shape[1],classes),dtype='float32')
        for j in range(votes.shape[1]):
            if j==held:
                continue
            rows=np.flatnonzero(votes[:,j]>=0)
            encoded[rows,j,votes[rows,j]]=1
        result.append(np.concatenate((base,encoded.reshape(len(votes),-1)),1))
    return np.stack(result,1)


def load_data(args):
    manifest=s4.read(args.root/'manifest.json')
    papers=manifest['papers']
    pids=[p['paper_id'] for p in papers]
    pindex={pid:i for i,pid in enumerate(pids)}
    classes=sorted({p['canonical_key'] for p in papers})
    vectors=np.load(args.root/'section_vectors.npz')
    position={int(pid):i for i,pid in enumerate(vectors['paper_ids'])}
    pv=np.array([vectors['vectors'][position[pid]] for pid in pids])
    masks=np.array([vectors['masks'][position[pid]] for pid in pids],dtype='float32')
    selected=providers(args)
    coarse=np.full((len(pids),len(selected)),-1,dtype='int64')
    for i,pid in enumerate(pids):
        for j,provider in enumerate(selected):
            vote=s4.read(args.root/'official_votes'/provider/f'{pid}.json')
            if vote.get('actual_provider',provider)!=provider and vote['actual_provider'] in selected:
                continue
            coarse[i,j]=classes.index(vote['canonical_key'])
    nodes=canonicalize(args)['nodes']
    per_paper=defaultdict(set)
    for row in canonicalize(args)['raw_mapping']:
        per_paper[row['paper_id']].add(row['canonical_id'])
    rows=[(pid,cid) for pid in pids for cid in sorted(per_paper[pid])]
    lookup={(pid,cid):i for i,(pid,cid) in enumerate(rows)}
    votes=np.full((len(rows),len(selected)),-1,dtype='int64')
    suppressed=Counter()
    for pid in pids:
        for j,provider in enumerate(selected):
            for vote in s4.read(args.root/'crosslabels'/provider/f'{pid}.json',[]):
                key=(pid,vote['id'])
                if key in lookup:
                    if vote.get('actual_provider',provider)!=provider and vote['actual_provider'] in selected:
                        suppressed[provider]+=1
                        continue
                    votes[lookup[key],j]={'yes':1,'no':0,'abstain':-1}[vote['vote']]
    s4.write(args.root/'vote_independence.json',{'providers':selected,
        'duplicate_replacement_observations_masked':dict(suppressed),
        'policy':'historical Kimi remains independent; GPT replacements use the original GPT observation once'})
    labels=np.load(args.root/'label_vectors.npz')
    label_index={cid:i for i,cid in enumerate(labels['ids'])}
    node_vectors=np.array([labels['vectors'][label_index[cid]] for pid,cid in rows])
    keywords=[s4.read(args.root/'raw'/f'{pid}.json')['metadata'].get('keywords') or [] for pid in pids]
    representations={}
    if (args.root/'paper_representations.npz').exists():
        combined=np.load(args.root/'paper_representations.npz')
        index={int(pid):i for i,pid in enumerate(combined['paper_ids'])}
        representations={name:combined[name][[index[pid] for pid in pids]] for name in PAPER_REPRESENTATIONS}
    return {'papers':papers,'pids':pids,'pindex':pindex,'classes':classes,'coarse':coarse,
            'gold':np.array([classes.index(p['canonical_key']) for p in papers]),
            'pv':pv,'masks':masks,'rows':rows,'votes':votes,'nodes':nodes,'nv':node_vectors,
            'fine_paper':np.array([pindex[pid] for pid,cid in rows]),'keywords':keywords,
            'providers':selected,'representations':representations}


def ece(probabilities,gold):
    confidence=probabilities.max(1)
    correct=probabilities.argmax(1)==gold
    result=0.
    for low in np.linspace(0,.9,10):
        selected=(confidence>=low)&(confidence<low+.1+1e-8)
        if selected.any():
            result+=selected.mean()*abs(correct[selected].mean()-confidence[selected].mean())
    return float(result)


def features(data,train,use_embedding,keyword_aux=True):
    # Gold labels and model self-votes are never part of the base feature matrix.
    selected=[s4.FIELDS.index(f) for f in PAPER_REPRESENTATIONS[use_embedding]] if isinstance(use_embedding,str) else list(range(len(s4.FIELDS)))
    masks=data['masks'][:,selected]
    base=masks.copy()
    fbase=np.column_stack([masks[data['fine_paper']],
                          np.eye(3)[[data['nodes'][cid]['level']-1 for pid,cid in data['rows']]],
                          np.eye(len(s4.FACETS))[[s4.FACETS.index(data['nodes'][cid]['facet']) for pid,cid in data['rows']]]]).astype('float32')
    if use_embedding:
        flat=data['representations'][use_embedding] if isinstance(use_embedding,str) else data['pv'].reshape(len(base),-1)
        pca=PCA(n_components=min(16,len(train)-1,flat.shape[1]),svd_solver='full').fit(flat[train])
        projected=pca.transform(flat).astype('float32')
        label_train=np.flatnonzero(np.isin(data['fine_paper'],train))
        lpca=PCA(n_components=min(16,len(label_train)-1,data['nv'].shape[1]),svd_solver='full').fit(data['nv'][label_train])
        labels=lpca.transform(data['nv']).astype('float32')
        base=np.column_stack((base,projected)).astype('float32')
        fbase=np.column_stack((fbase,projected[data['fine_paper']],labels)).astype('float32')
    vocab=Counter(normalized(k) for i in train for k in data['keywords'][i])
    keys=[k for k,n in vocab.most_common(64)]
    targets=np.zeros((len(base),max(1,len(keys))),dtype='float32')
    for i,values in enumerate(data['keywords']):
        for keyword in values:
            if normalized(keyword) in keys:
                targets[i,keys.index(normalized(keyword))]=1
    targets/=np.maximum(targets.sum(1,keepdims=True),1)
    return base,fbase,targets


def train_network(data,train,valid,test,seed,use_embedding,conditional=True,transfer=True,keyword_aux=True,omit=None):
    import torch
    from torch import nn
    import torch.nn.functional as F
    torch.manual_seed(seed)
    torch.set_num_threads(4)
    base,fbase,keywords=features(data,train,use_embedding,keyword_aux)
    coarse=data['coarse'].copy()
    n_models=coarse.shape[1]
    fine=data['votes'].copy()
    if omit is not None:
        coarse[:,omit]=-1
        fine[:,omit]=-1
    cviews=torch.tensor(masked_views(base,coarse,len(data['classes'])))
    fviews=torch.tensor(masked_views(fbase,fine,2))
    gold=torch.tensor(data['gold'])
    cv=torch.tensor(coarse)
    fv=torch.tensor(fine)
    targets=torch.tensor(keywords)
    fp=torch.tensor(data['fine_paper'])
    ctrain=torch.tensor(train)
    cvalid=torch.tensor(valid)
    ftrain=torch.tensor(np.flatnonzero(np.isin(data['fine_paper'],train)))

    class Crowd(nn.Module):
        def __init__(self):
            super().__init__()
            def mlp(size,out):
                return nn.Sequential(nn.Linear(size,32),nn.ReLU(),nn.Dropout(.2),nn.Linear(32,out))
            k=len(data['classes'])
            self.official=mlp(cviews.shape[-1],k)
            self.free=mlp(fviews.shape[-1],2)
            self.keyword=mlp(cviews.shape[-1],keywords.shape[-1])
            self.coarse_confusion=nn.Parameter(torch.eye(k).repeat(n_models,1,1)*2)
            self.fine_confusion=nn.Parameter(torch.eye(2).repeat(n_models,1,1)*2)
            self.cgate=mlp(cviews.shape[-1],1)
            self.fgate=mlp(fviews.shape[-1],1)

        def distributions(self,views,head,confusion,gate):
            truth=head(views).softmax(-1)
            global_noise=confusion.softmax(-1)
            expanded=global_noise.unsqueeze(0).expand(len(views),-1,-1,-1)
            if conditional:
                reliability=gate(views).sigmoid().unsqueeze(-1)
                identity=torch.eye(confusion.shape[-1]).view(1,1,confusion.shape[-1],confusion.shape[-1])
                noise=reliability*expanded+(1-reliability)*identity
            else:
                noise=expanded
            observed=torch.einsum('nmt,nmtl->nml',truth,noise)
            return truth,observed,noise

    model=Crowd()
    optimizer=torch.optim.AdamW(model.parameters(),lr=1e-3,weight_decay=1e-2)
    best=None
    best_loss=float('inf')
    stale=0
    # Parent pair positions are fixed from candidate provenance, not from observed official gold.
    row_lookup={row:i for i,row in enumerate(data['rows'])}
    parent_pairs=[]
    for i,(pid,cid) in enumerate(data['rows']):
        for parent in data['nodes'][cid]['parents']:
            if (pid,parent) in row_lookup:
                parent_pairs.append((i,row_lookup[(pid,parent)]))
    parent_pairs=torch.tensor(parent_pairs,dtype=torch.long).reshape(-1,2)

    def crowd_loss(prediction,observed,selection):
        values=prediction[selection].reshape(-1,prediction.shape[-1])
        labels=observed[selection].reshape(-1)
        mask=labels>=0
        return F.nll_loss(values[mask].clamp_min(1e-8).log(),labels[mask]) if mask.any() else values.sum()*0

    for epoch in range(200):
        model.train()
        optimizer.zero_grad()
        ct,cp,cn=model.distributions(cviews,model.official,model.coarse_confusion,model.cgate)
        ft,fpred,fn=model.distributions(fviews,model.free,model.fine_confusion,model.fgate)
        loss=F.nll_loss(ct[ctrain].mean(1).clamp_min(1e-8).log(),gold[ctrain])
        # Official labels anchor the coarse confusion directly; hidden answers never enter inputs.
        gold_noise=cn[ctrain[:,None],torch.arange(n_models)[None,:],gold[ctrain,None],:]
        loss+=crowd_loss(gold_noise,cv[ctrain],torch.arange(len(ctrain)))
        loss+=crowd_loss(fpred,fv,ftrain)
        if keyword_aux:
            kpred=model.keyword(cviews[ctrain]).mean(1).log_softmax(-1)
            known=targets[ctrain].sum(-1)>0
            if known.any():
                loss+=.1*(-(targets[ctrain][known]*kpred[known]).sum(-1).mean())
        if transfer:
            coarse_rel=model.coarse_confusion.softmax(-1).diagonal(dim1=-2,dim2=-1).mean(-1)
            fine_rel=model.fine_confusion.softmax(-1).diagonal(dim1=-2,dim2=-1).mean(-1)
            loss+=.1*((coarse_rel-fine_rel)**2).mean()
        if conditional:
            loss+=.01*(model.cgate(cviews[ctrain]).sigmoid().square().mean()+model.fgate(fviews[ftrain]).sigmoid().square().mean())
        if len(parent_pairs):
            pairmask=torch.isin(fp[parent_pairs[:,0]],ctrain)
            pp=parent_pairs[pairmask]
            if len(pp):
                probs=ft.mean(1)[:,1]
                loss+=.1*F.relu(probs[pp[:,0]]-probs[pp[:,1]]).mean()
        loss.backward()
        optimizer.step()
        model.eval()
        with torch.no_grad():
            prediction=model.official(cviews[cvalid]).softmax(-1).mean(1)
            validation=F.nll_loss(prediction.clamp_min(1e-8).log(),gold[cvalid]).item()
        if validation<best_loss-1e-5:
            best_loss=validation
            best={k:v.detach().clone() for k,v in model.state_dict().items()}
            stale=0
        else:
            stale+=1
        if stale>=15:
            break
    model.load_state_dict(best)
    model.eval()
    with torch.no_grad():
        cprob=model.official(cviews).softmax(-1).mean(1).numpy()
        fprob=model.free(fviews).softmax(-1).mean(1)[:,1].numpy()
        # Posterior update explicitly incorporates independent noisy votes through the learned confusion.
        _,_,noise=model.distributions(fviews,model.free,model.fine_confusion,model.fgate)
        logpost=np.column_stack((np.log(np.maximum(1-fprob,1e-8)),np.log(np.maximum(fprob,1e-8))))
        noise=noise.numpy()
        for j in range(n_models):
            for observed in (0,1):
                selected=fine[:,j]==observed
                logpost[selected]+=np.log(np.maximum(noise[selected,j,:,observed],1e-8))
        logpost-=logpost.max(1,keepdims=True)
        posterior=np.exp(logpost)
        posterior/=posterior.sum(1,keepdims=True)
    return {'coarse':cprob,'fine':posterior[:,1], 'fine_prior':fprob, 'fine_noise':noise, 'epochs':epoch+1,
            'coarse_confusion':model.coarse_confusion.softmax(-1).detach().numpy(),
            'fine_confusion':model.fine_confusion.softmax(-1).detach().numpy()},best


def fit(args):
    import torch
    data=load_data(args)
    s4.write(args.root/'fusion_rows.json',data['rows'])
    ds,confusion=dawid_skene(data['votes'])
    np.savez_compressed(args.root/'ds_baseline.npz',posterior=ds,confusion=confusion,majority=majority(data['votes']))
    groups=np.array([p['group_key'] for p in data['papers']])
    folds=list(GroupKFold(n_splits=5).split(data['pids'],groups=groups))
    configs=[('E0',False,True,True,True,None),('E1',True,True,True,True,None),
             ('static',True,False,True,True,None),('no_transfer',True,True,False,True,None),
             ('no_keywords',True,True,True,False,None)]
    configs += [(name,rep,True,True,True,None) for name,rep in
                (('TA','title_abstract'),('TAK','title_abstract_keywords')) if rep in data['representations']]
    configs += [(f'without_{provider}',True,True,True,True,j) for j,provider in enumerate(providers(args))]
    for name,embedding,conditional,transfer,keyword,omit in configs:
        all_coarse=[]
        all_fine=[]
        all_prior=[]
        all_noise=[]
        for seed in (1701,1702,1703,1704,1705):
            oof=np.zeros((len(data['pids']),len(data['classes'])))
            fine=np.full(len(data['rows']),np.nan)
            prior=np.full(len(data['rows']),np.nan)
            noise=np.zeros((len(data['rows']),len(providers(args)),2,2),dtype='float32')
            for fold,(training,test) in enumerate(folds):
                target=args.root/'models'/name/f'{seed}_{fold}.npz'
                if target.exists():
                    result=dict(np.load(target))
                else:
                    # Validation is group-disjoint within the outer training fold.
                    train_groups=sorted(set(groups[training]),key=lambda x:s4.digest([seed,x]))
                    val_groups=set(train_groups[:max(1,len(train_groups)//5)])
                    valid=np.array([i for i in training if groups[i] in val_groups])
                    train=np.array([i for i in training if groups[i] not in val_groups])
                    result,state=train_network(data,train,valid,test,seed,embedding,conditional,transfer,keyword,omit)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    np.savez_compressed(target,**result)
                    torch.save(state,target.with_suffix('.pt'))
                    s4.log('fold_complete',configuration=name,seed=seed,fold=fold,epochs=result['epochs'])
                oof[test]=result['coarse'][test]
                selected=np.isin(data['fine_paper'],test)
                fine[selected]=result['fine'][selected]
                prior[selected]=result['fine_prior'][selected]
                noise[selected]=result['fine_noise'][selected]
            all_coarse.append(oof)
            all_fine.append(fine)
            all_prior.append(prior)
            all_noise.append(noise)
        coarse=np.mean(all_coarse,axis=0)
        posterior=np.mean(all_fine,axis=0)
        np.savez_compressed(args.root/f'posterior_{name}.npz',coarse=coarse,fine=posterior,seeds=np.array(all_fine),
                            fine_prior=np.mean(all_prior,axis=0),fine_noise=np.mean(all_noise,axis=0))
        s4.write(args.root/f'metrics_{name}.json',{'role':'development_oof_transductive_taxonomy',
            'providers':list(providers(args)),
            'paper_representation':embedding if isinstance(embedding,str) else ('six_sections' if embedding else 'no_embedding'),
            'official_macro_f1':float(f1_score(data['gold'],coarse.argmax(1),average='macro',zero_division=0)),
            'official_micro_f1':float(f1_score(data['gold'],coarse.argmax(1),average='micro')),
            'official_ece':ece(coarse,data['gold']), 'fine_gold_available':False,
            'fine_mean_entropy':float(np.mean(-posterior*np.log(np.maximum(posterior,1e-8))-(1-posterior)*np.log(np.maximum(1-posterior,1e-8)))),
            'fine_seed_std':float(np.std(all_fine,axis=0).mean())})
    s4.write(args.root/'fusion_complete.json',{'completed_at':s4.now(),'configs':[c[0] for c in configs]})


def repair(args):
    data=load_data(args)
    nodes=canonicalize(args)['nodes']
    rows=[tuple(row) for row in s4.read(args.root/'fusion_rows.json')]
    pairs=semantic_pairs(args)
    votes=s4.read(args.root/'alignment_votes.json')
    vote_map={provider:{v['id']:v for v in values} for provider,values in votes.items()}
    hierarchy=s4.read(args.root/'hierarchy_votes.json')
    edge_votes={provider:{v['id']:v for v in values} for provider,values in hierarchy['votes'].items()}
    approved_edges={(edge['parent_id'],edge['child_id']) for edge in hierarchy['edges']
                    if scope_approved({p:edge_votes[p].get(edge['id'],{'vote':'abstain'}) for p in providers(args)})}
    arms=['E0','E1']+[name for name in ('TA','TAK') if (args.root/f'posterior_{name}.npz').exists()]
    for representation in arms:
        fitted=np.load(args.root/f'posterior_{representation}.npz')
        posterior=fitted['fine']
        for do_repair in (0,1):
            parent={cid:cid for cid in nodes}
            def find(cid):
                while parent[cid]!=cid:
                    cid=parent[cid]
                return cid
            operations=[]
            if do_repair:
                for pair in pairs:
                    entries={p:vote_map[p].get(pair['id'],{'vote':'abstain'}) for p in providers(args)}
                    decisions={p:vote['vote'] for p,vote in entries.items()}
                    accepted=scope_approved(entries)
                    if accepted:
                        a,b=find(pair['a']),find(pair['b'])
                        parent[b]=a
                    operations.append({**pair,'operation':'merge' if accepted else 'keep_separate',
                                       'votes':decisions,'independent_votes':{p:v['vote'] for p,v in independent_votes(entries).items()},
                                       'reason':'equivalent_scope_vote' if accepted else 'insufficient_equivalence'})
            output_nodes={}
            for cid,node in nodes.items():
                root=find(cid)
                if root not in output_nodes:
                    output_nodes[root]={**nodes[root],'id':root,'members':[],'parents':[],'aliases':[]}
                output_nodes[root]['members'].extend(node['members'])
                output_nodes[root]['aliases'].append(cid)
                output_nodes[root]['parents'].extend(find(p) for p in node['parents'] if (p,cid) in approved_edges)
            for node in output_nodes.values():
                node['parents']=sorted(set(node['parents']))
                assert all(output_nodes[p]['level']==node['level']-1 for p in node['parents'])
            reachable={cid for cid,node in output_nodes.items() if node['level']==1}
            for level in (2,3):
                for cid,node in output_nodes.items():
                    if node['level']==level:
                        node['parents']=[p for p in node['parents'] if p in reachable]
                        if node['parents']:
                            reachable.add(cid)
            assignments={}
            merged_rows=defaultdict(list)
            for i,(pid,cid) in enumerate(rows):
                merged_rows[(pid,find(cid))].append(i)
            for key,members in merged_rows.items():
                if not do_repair or len(members)==1:
                    assignments[key]=float(posterior[members[0]])
                    continue
                # Recompute merged posterior from pre-observation priors and each
                # annotator once. Conflicting alias votes become missing, never extra votes.
                prior=float(np.mean(fitted['fine_prior'][members]))
                noise=fitted['fine_noise'][members].mean(0)
                logpost=np.log(np.maximum([1-prior,prior],1e-8))
                for j in range(data['votes'].shape[1]):
                    observed=set(int(v) for v in data['votes'][members,j] if v>=0)
                    if len(observed)==1:
                        logpost+=np.log(np.maximum(noise[j,:,observed.pop()],1e-8))
                logpost-=logpost.max()
                probabilities=np.exp(logpost)
                assignments[key]=float(probabilities[1]/probabilities.sum())
            # Only high-support nodes are activated; closure is then a hard invariant.
            active=set()
            for cid,node in output_nodes.items():
                papers={pid for (pid,key),score in assignments.items() if key==cid and score>=.9}
                models={m['provider'] for m in node['members']}
                if len(papers)>=2 and len(models)>=2:
                    if node['level']==1 or node['parents']:
                        active.add(cid)
            for cid in sorted(active,key=lambda c:output_nodes[c]['level'],reverse=True):
                stack=list(output_nodes[cid]['parents'])
                while stack:
                    p=stack.pop()
                    active.add(p)
                    stack.extend(output_nodes[p]['parents'])
            final={key:score for key,score in assignments.items() if key[1] in active and score>=.9}
            for (pid,cid),score in list(final.items()):
                stack=list(output_nodes[cid]['parents'])
                while stack:
                    p=stack.pop()
                    final[(pid,p)]=max(final.get((pid,p),0.),score)
                    stack.extend(output_nodes[p]['parents'])
            arm=f'{representation}R{do_repair}'
            result={'arm':arm,'providers':list(providers(args)),'nodes':output_nodes,
                    'active_nodes':sorted(active),'operations':operations,
                    'assignments':[{'paper_id':pid,'node_id':cid,'score':score,'score_type':'latent_posterior'} for (pid,cid),score in sorted(final.items())],
                    'score_warning':'Uncalibrated latent posterior; no fine-grained gold accuracy available.'}
            s4.write(args.root/f'taxonomy_{arm}.json',result)
            label_data=np.load(args.root/'label_vectors.npz')
            label_index={cid:i for i,cid in enumerate(label_data['ids'])}
            repaired_vectors=[]
            repaired_ids=sorted(output_nodes)
            for cid in repaired_ids:
                vector=label_data['vectors'][[label_index[a] for a in output_nodes[cid]['aliases']]].mean(0)
                repaired_vectors.append(vector/max(np.linalg.norm(vector),1e-12))
            np.savez_compressed(args.root/f'repaired_vectors_{arm}.npz',
                                ids=np.array(repaired_ids),vectors=np.array(repaired_vectors))
    s4.write(args.root/'repair_complete.json',{'completed_at':s4.now()})


def persist(args):
    """Idempotent experimental writes. Latent scores are never stored as probabilities."""
    manifest=s4.read(args.root/'manifest.json')
    taxonomy_version=manifest['version']
    if manifest.get('ablation'):
        raise ValueError('Ablation artifacts cannot overwrite the main experiment version')
    result=s4.read(args.root/'taxonomy_E1R1.json')
    vectors=np.load(args.root/'section_vectors.npz')
    papers={p['paper_id']:p for p in manifest['papers']}
    node_ids={}
    names=Counter((n['level'],n['name']) for n in result['nodes'].values())
    with psycopg.connect(args.database_url) as conn:
        if manifest.get('source_root'):
            config={'providers':providers(args),'role_replacement':replacements(args),'representations':PAPER_REPRESENTATIONS,
                    'source_root':manifest['source_root'],'revision':s4.REVISION}
            conn.execute('''INSERT INTO semantic.taxonomy_version(taxonomy_version,status,profile_version,
                dataset_snapshot_id,split_manifest_hash,config_hash,code_commit,parent_version,metadata)
                SELECT %s,'experimental',profile_version,dataset_snapshot_id,split_manifest_hash,%s,
                    code_commit,taxonomy_version,%s FROM semantic.taxonomy_version WHERE taxonomy_version=%s
                ON CONFLICT(taxonomy_version) DO NOTHING''',
                (taxonomy_version,s4.digest(config),Jsonb(config),manifest['parent_version']))
            conn.execute('''INSERT INTO semantic.taxonomy_split(taxonomy_version,paper_id,split,group_key,manifest_hash)
                SELECT %s,paper_id,split,group_key,manifest_hash FROM semantic.taxonomy_split
                WHERE taxonomy_version=%s ON CONFLICT DO NOTHING''',(taxonomy_version,manifest['parent_version']))
        version=conn.execute('SELECT status FROM semantic.taxonomy_version WHERE taxonomy_version=%s',(taxonomy_version,)).fetchone()
        if not version or version[0]!='experimental':
            raise ValueError('Persistence requires registered experimental version')
        for cid,node in result['nodes'].items():
            name=node['name'] if names[(node['level'],node['name'])]==1 else node['name']+' ['+cid[:8]+']'
            status='accepted' if cid in result['active_nodes'] else 'model_reviewed'
            row=conn.execute('''INSERT INTO semantic.taxonomy_node
                (taxonomy_version,level,name,definition,stable_key,facet_type,inclusion_criteria,
                 exclusion_criteria,review_status,metadata,provenance)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(taxonomy_version,stable_key) WHERE stable_key IS NOT NULL DO NOTHING
                RETURNING taxonomy_node_id''',
                (taxonomy_version,node['level'],name,node['definition'],cid,node['facet'],
                 Jsonb(node.get('inclusion_criteria',[])),Jsonb(node.get('exclusion_criteria',[])),status,
                 Jsonb({'aliases':node['aliases'],'arm':'E1R1'}),
                 Jsonb({'method':'multi_model_crowd_layer','providers':providers(args),'evidence':node['members'],'human_review':False}))).fetchone()
            node_ids[cid]=row[0] if row else conn.execute('SELECT taxonomy_node_id FROM semantic.taxonomy_node WHERE taxonomy_version=%s AND stable_key=%s',(taxonomy_version,cid)).fetchone()[0]
        for cid,node in result['nodes'].items():
            for parent in node['parents']:
                evidence=[{'paper_id':m['paper_id'],'provider':m['provider'],'quotes':m['evidence']} for m in node['members']]
                years=[papers[m['paper_id']]['year'] for m in node['members']]
                conn.execute('''INSERT INTO semantic.taxonomy_edge(taxonomy_version,source_node_id,target_node_id,
                    relation_type,score,support_count,first_year,last_year,evidence,provenance)
                    VALUES(%s,%s,%s,'parent_of',1,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                    (taxonomy_version,node_ids[parent],node_ids[cid],len(set(m['paper_id'] for m in node['members'])),
                     min(years),max(years),Jsonb(evidence),Jsonb({'source':'multi_model_scope_containment_vote','providers':providers(args),'score_semantics':'structural_edge_not_calibrated_probability',
                         'vote_artifact':str(args.root/'hierarchy_votes.json')})))
        embedding_ids={}
        stats=s4.read(args.root/'embedding_stats.json')
        for j,field in enumerate(s4.FIELDS):
            spec_key=s4.digest({'model':'BAAI/bge-m3','revision':s4.REVISION,'field':field,'chunk':512,'overlap':64})
            spec=conn.execute('''INSERT INTO semantic.embedding_spec(spec_key,model_name,model_revision,
                representation_key,dimension,configuration) VALUES(%s,'BAAI/bge-m3',%s,%s,1024,%s)
                ON CONFLICT(spec_key) DO UPDATE SET spec_key=EXCLUDED.spec_key RETURNING embedding_spec_id''',
                (spec_key,s4.REVISION,field,Jsonb(stats))).fetchone()[0]
            for i,raw_pid in enumerate(vectors['paper_ids']):
                pid=int(raw_pid)
                if not vectors['masks'][i,j]:
                    continue
                section=s4.read(args.root/'sections'/f'{pid}.json')[field]
                model_name='BAAI/bge-m3:'+s4.REVISION+':'+field
                literal='['+','.join(str(float(x)) for x in vectors['vectors'][i,j])+']'
                row=conn.execute('''INSERT INTO semantic.embedding(paper_id,model_name,content_hash,embedding,
                    embedding_spec_id,taxonomy_version,metadata) VALUES(%s,%s,%s,%s::vector,%s,%s,%s)
                    ON CONFLICT(paper_id,model_name,content_hash) DO NOTHING RETURNING embedding_id''',
                    (pid,model_name,section['content_hash'],literal,spec,taxonomy_version,
                     Jsonb({'section':field,'raw_input_hash':papers[pid]['raw_input_hash']}))).fetchone()
                embedding_ids[(pid,field)]=row[0] if row else conn.execute('SELECT embedding_id FROM semantic.embedding WHERE paper_id=%s AND model_name=%s AND content_hash=%s',(pid,model_name,section['content_hash'])).fetchone()[0]
        for assignment in result['assignments']:
            pid=assignment['paper_id']
            cid=assignment['node_id']
            evidence=[quote for m in result['nodes'][cid]['members'] if m['paper_id']==pid for quote in m['evidence']]
            conn.execute('''INSERT INTO semantic.paper_taxonomy_assignment
                (paper_id,taxonomy_node_id,score,source,taxonomy_version,score_type,embedding_id,input_hash,evidence,provenance)
                VALUES(%s,%s,%s,'crowd_layer_E1R1',%s,'judge_proxy',%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                (pid,node_ids[cid],assignment['score'],taxonomy_version,embedding_ids.get((pid,'abstract')),
                 papers[pid]['raw_input_hash'],Jsonb(evidence),
                 Jsonb({'score_semantics':'uncalibrated_latent_posterior','human_gold_available':False,
                        'parent_closure_enforced':True})))
        conn.execute('UPDATE semantic.taxonomy_version SET metadata=metadata || %s WHERE taxonomy_version=%s',
                     (Jsonb({'artifacts_root':str(args.root),'postprocess_completed_at':s4.now(),
                             'providers':providers(args),'fine_gold_available':False,'s3_frozen':False}),taxonomy_version))
        counts={table:conn.execute('SELECT count(*) FROM semantic.'+table+' WHERE taxonomy_version=%s',(taxonomy_version,)).fetchone()[0]
                for table in ('taxonomy_node','taxonomy_edge','paper_taxonomy_assignment','embedding')}
    s4.write(args.root/'persistence.json',counts)
    s4.log('experimental_persisted',**counts)


def report(args):
    counts=Counter()
    tokens=Counter()
    for path in (args.root/'attempts').glob('*/*.json'):
        item=s4.read(path)
        if item.get('provider') not in providers(args):
            continue
        counts[item.get('status','unknown')]+=1
        if item.get('error_kind'):
            counts[item['error_kind']]+=1
        for key,value in item.get('usage',{}).items():
            if isinstance(value,int):
                tokens[key]+=value
    version=s4.read(args.root/'manifest.json')['version']
    summary={'version':version,'created_at':s4.now(),'evaluation_role':'development_only',
             'providers':providers(args),'role_replacement':replacements(args),
             'vote_independence':s4.read(args.root/'vote_independence.json'),
             'paper_representations':PAPER_REPRESENTATIONS,
             'attempts':dict(counts),'usage':dict(tokens),'fine_gold_available':False,
             'production_quality_accepted':False,'persistence':s4.read(args.root/'persistence.json'),
             'metrics':{p.stem:s4.read(p) for p in args.root.glob('metrics_*.json')}}
    s4.write(args.root/'summary.json',summary)
    # Report is an experiment output, never evidence of a production freeze.
    lines=['# S4 v4 实验报告','',f'版本：{version}；更新时间：{s4.now()}。',
           '','200 篇均为开发数据。细粒度无独立 gold，结果不构成生产质量验收。','',
           '```json',json.dumps(summary,ensure_ascii=False,indent=2),'```','']
    target=args.root/'report.md'
    temp=target.with_suffix('.md.tmp')
    temp.write_text('\n'.join(lines))
    temp.replace(target)


def related_work_ablation(args):
    """A real input ablation: regenerate votes, never merely erase text after inference."""
    if replacements(args):
        # Compare unchanged generators on both sides; replacing Kimi changes its model.
        root=args.root/'ablations/unchanged_provider_control'
        control=argparse.Namespace(root=root,source_root=args.root,
            providers=[p for p in providers(args) if p not in replacements(args)])
        prepare_branch(control)
        manifest=s4.read(root/'manifest.json')
        manifest['ablation']='unchanged_provider_control'
        s4.write(root/'manifest.json',manifest)
        subprocess.run([os.sys.executable,__file__,'watch','--root',str(root),'--auth',str(args.auth),
            '--database-url',args.database_url,'--providers',*control.providers],check=True)
        s4.write(args.root/'related_work_ablation_complete.json',{'control_root':str(root),
            'comparison_providers':control.providers,'completed_at':s4.now()})
        return
    root=args.root/'ablations/no_related_work'
    if not (root/'manifest.json').exists():
        manifest=copy.deepcopy(s4.read(args.root/'manifest.json'))
        manifest.update(version=manifest['version']+'_no_related_work',ablation='remove_related_work_before_generation')
        manifest.pop('source_root',None)
        for paper in manifest['papers']:
            pid=paper['paper_id']
            s4.write(root/'raw'/f'{pid}.json',s4.read(args.root/'raw'/f'{pid}.json'))
            sections=s4.read(args.root/'sections'/f'{pid}.json')
            sections['related_work'].update(text='',missing=True,spans=[],content_hash=s4.digest(''),
                                            omission_reason='controlled_input_ablation')
            s4.write(root/'sections'/f'{pid}.json',sections)
        source=np.load(args.root/'section_vectors.npz')
        vectors=source['vectors'].copy()
        masks=source['masks'].copy()
        j=s4.FIELDS.index('related_work')
        vectors[:,j]=0
        masks[:,j]=False
        np.savez_compressed(root/'section_vectors.npz',vectors=vectors,masks=masks,paper_ids=source['paper_ids'])
        s4.write(root/'embedding_stats.json',{**s4.read(args.root/'embedding_stats.json'),
                 'ablation':'related_work_masked','source_vectors':str(args.root/'section_vectors.npz')})
        s4.write(root/'local_server.json',s4.read(args.root/'local_server.json'))
        s4.write(root/'manifest.json',manifest)
    s4.log('related_work_ablation_started',root=str(root))
    subprocess.run([os.sys.executable,str(Path(s4.__file__)),'run','--root',str(root),'--auth',str(args.auth),
                    '--database-url',args.database_url,'--providers',*[p for p in providers(args) if p!='kimi']],check=True)
    if 'kimi' in providers(args):
        subprocess.run([os.sys.executable,str(Path(kimi_batch.__file__)),'--root',str(root),'--auth',str(args.auth)],check=True)
    subprocess.run([os.sys.executable,__file__,'watch','--root',str(root),'--auth',str(args.auth),
                    '--database-url',args.database_url,'--skip-related-work-ablation',
                    '--providers',*providers(args)],check=True)
    s4.write(args.root/'related_work_ablation_complete.json',{'root':str(root),'completed_at':s4.now()})


def watch(args):
    prepare_branch(args)
    s4.write(args.root/'postprocess_execution.json',{'status':'waiting_for_generation','pid':os.getpid(),'started_at':s4.now()})
    s4.write(args.root/'fusion_code.json',{'code':Path(__file__).read_text(),'code_hash':s4.digest(Path(__file__).read_text())})
    papers=s4.read(args.root/'manifest.json')['papers']
    while not all(all(str(level) in s4.read(args.root/'generated'/p/f'{paper["paper_id"]}.json',{})
                      for level in (1,2,3)) and (args.root/'official_votes'/p/f'{paper["paper_id"]}.json').exists()
                  for p in providers(args) for paper in papers):
        state=s4.read(args.root/'execution.json',{})
        if state.get('status')=='failed':
            raise RuntimeError('Generation failed; fusion will not proceed with incomplete model votes')
        time.sleep(30)
    canonicalize(args)
    s4.write(args.root/'postprocess_execution.json',{'status':'running','pid':os.getpid(),'started_at':s4.now()})
    if source_root(args):
        s4.write(args.root/'postprocess_execution.json',{'status':'waiting_for_source_crosslabels',
            'providers':providers(args),'pid':os.getpid(),'started_at':s4.now()})
        crosslabel(args)
    if not (args.root/'label_vectors.npz').exists() or not (args.root/'paper_representations.npz').exists():
        owned=s4.read(args.root/'local_server.json')
        if not owned:
            raise RuntimeError('Qwen service ownership unknown; refusing to evict another GPU workload')
        subprocess.run(['systemctl','--user','stop',owned['unit']],check=True)
        subprocess.run([os.sys.executable,__file__,'embed-analysis','--root',str(args.root)],check=True)
        s4.start_local(args)
    s4.write(args.root/'postprocess_execution.json',{'status':'running','providers':providers(args),
        'pid':os.getpid(),'updated_at':s4.now()})
    align(args)
    if not source_root(args):
        crosslabel(args)
    validate_hierarchy(args)
    fit(args)
    repair(args)
    if not s4.read(args.root/'manifest.json').get('ablation'):
        persist(args)
    report(args)
    s4.write(args.root/'postprocess_complete.json',{'completed_at':s4.now(),'status':'experimental_outputs_ready_not_production_accepted'})
    if not args.skip_related_work_ablation:
        related_work_ablation(args)
    s4.write(args.root/'postprocess_execution.json',{'status':'complete','pid':os.getpid(),'ended_at':s4.now()})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('watch','canonicalize','label-embed','embed-analysis','align','crosslabel','fit','repair','persist','report'))
    parser.add_argument('--root',type=Path,default=s4.ROOT)
    parser.add_argument('--auth',type=Path,default=Path(os.environ.get('ICLR_AUTH_FILE', Path.home()/'auth')))
    parser.add_argument('--database-url',default=os.environ.get('ICLR_DATABASE_URL', 'host=127.0.0.1 port=55432 dbname=iclr_reviewer'))
    parser.add_argument('--skip-related-work-ablation',action='store_true')
    parser.add_argument('--providers',nargs='+',choices=s4.PROVIDERS)
    parser.add_argument('--source-root',type=Path,help='Create an isolated branch and reuse completed source cross-votes')
    parser.add_argument('--replace-kimi-with-openai',action='store_true',
        help='Retain historical Kimi work; route only missing evaluation jobs to OpenAI, deduplicating GPT votes')
    args=parser.parse_args()
    args.root.mkdir(parents=True,exist_ok=True)
    stages={'watch':watch,'canonicalize':canonicalize,'label-embed':label_embed,'embed-analysis':embed_analysis,'align':align,
            'crosslabel':crosslabel,'fit':fit,'repair':repair,'persist':persist,'report':report}
    with (args.root/f'fusion_{args.stage}.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            stages[args.stage](args)
        except Exception as error:
            s4.write(args.root/'fusion_failure.json',{'stage':args.stage,'error':type(error).__name__,
                      'message':str(error),'created_at':s4.now()})
            s4.write(args.root/'postprocess_execution.json',{'status':'failed','stage':args.stage,'pid':os.getpid(),
                      'error':type(error).__name__,'ended_at':s4.now()})
            raise


if __name__=='__main__':
    main()
