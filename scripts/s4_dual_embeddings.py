#!/usr/bin/env python3
"""Encode every supplied text view with both pinned, native embedding models."""
import gc
import hashlib
from pathlib import Path

try:
    from .deployment_paths import storage_path
except ImportError:
    from deployment_paths import storage_path
import time

import numpy as np

from s4_reproduce500 import BGE, digest, log, now, read, write

QWEN = storage_path('iclr-s4/models/models--Qwen--Qwen3-Embedding-0.6B/snapshots/97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3')
MODELS = [('bge-m3', 'BAAI/bge-m3', BGE, 'cls'),
          ('qwen3-embedding-0.6b', 'Qwen/Qwen3-Embedding-0.6B', QWEN, 'lasttoken')]
MAX_LENGTH = 8192
BATCH = 8


def checked_vectors(path, signature, ids):
    with np.load(path, allow_pickle=False) as data:
        if str(data['signature']) != signature or data['paper_ids'].tolist() != ids:
            raise ValueError(f'Embedding checkpoint/input mismatch: {path}')
        vectors = data['vectors'].copy()
    if (vectors.shape != (len(ids), 1024) or not np.isfinite(vectors).all()
            or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=2e-5)):
        raise ValueError(f'Invalid embedding vectors: {path}')
    return vectors


def save_vectors(path, vectors, signature, ids, hashes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('wb') as out:
        np.savez_compressed(out, vectors=vectors, signature=signature,
                            paper_ids=np.asarray(ids), input_hashes=np.asarray(hashes))
    temp.replace(path)
    return checked_vectors(path, signature, ids)


def encode_all(root, rows, progress, views=None):
    """Any additional view passed here automatically receives both model versions."""
    from sentence_transformers import SentenceTransformer
    import torch
    root = Path(root)
    views = views if views is not None else {
        'abstract': [r['abstract'] for r in rows], 'core': [r['core_text'] for r in rows]}
    ids = [r['paper_id'] for r in rows]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError('Paper IDs must be nonempty and unique')
    if any(len(texts) != len(ids) or any(not t.strip() for t in texts) for texts in views.values()):
        raise ValueError('Every view requires one nonempty text per paper')
    torch.set_num_threads(8)
    all_meta = read(root/'embeddings/metadata.json') if (root/'embeddings/metadata.json').exists() else {}
    progress.data.update(embedding_total=len(ids)*len(views)*len(MODELS), embedding_completed=0)
    for slug, model_id, model_path, pooling in MODELS:
        model, loaded_device = None, None
        for view, texts in views.items():
            # Completed views keep their actual execution device and exact cached vectors.
            device = all_meta.get(view, {}).get(slug, {}).get('device') or (
                'cuda:0' if torch.cuda.is_available() else 'cpu')
            if device != loaded_device:
                if device.startswith('cuda') and not torch.cuda.is_available():
                    raise RuntimeError('GPU embedding checkpoint requires CUDA; no silent device change')
                del model
                gc.collect()
                log('embedding_model_load', model=model_id, device=device)
                kwargs = {'torch_dtype': torch.float32, 'use_safetensors': slug != 'bge-m3'}
                model = SentenceTransformer(str(model_path), device=device, local_files_only=True,
                    model_kwargs=kwargs, processor_kwargs={'padding_side': 'left'} if pooling == 'lasttoken' else {})
                model.max_seq_length = MAX_LENGTH
                if model.default_prompt_name:
                    raise ValueError('An implicit prompt would alter the saved text input')
                loaded_device = device
            native_pooling = model[1].get_config_dict()
            if native_pooling.get('pooling_mode') != pooling:
                raise ValueError('Unexpected native pooling')
            hashes = [hashlib.sha256(t.encode()).hexdigest() for t in texts]
            directory = root/'embeddings'/slug
            output = directory/f'{view}.npz'
            config = dict(model=model_id, revision=model_path.name, device=device, dtype='float32',
                max_seq_length=MAX_LENGTH, pooling=native_pooling, normalize=True, instruction=None,
                text_policy='Exact complete input; reject overlength; no truncation or chunk averaging')
            signature = digest(dict(config=config, paper_ids=ids, input_hashes=hashes))
            progress.data.update(phase=f'embedding {model_id} / {view}', batch=f'{slug}/{view}',
                batch_total=len(ids), batch_completed=0, embedding_seconds_per_item=None)
            progress.save()
            # Preflight every input, including cache hits, to prevent silent truncation.
            lengths = [len(model.tokenizer.encode(t, add_special_tokens=True)) for t in texts]
            if max(lengths) > MAX_LENGTH:
                raise ValueError(f'{model_id}/{view} input exceeds {MAX_LENGTH}; explicit windowing required')
            all_vectors = []
            for start in range(0, len(ids), BATCH):
                end = min(start+BATCH, len(ids))
                batch_ids, batch_hashes = ids[start:end], hashes[start:end]
                part = directory/'checkpoints'/f'{view}-{start:05d}.npz'
                part_signature = digest(dict(config=config, paper_ids=batch_ids, input_hashes=batch_hashes))
                tick = time.monotonic()
                cached = part.exists()
                if cached:
                    vec = checked_vectors(part, part_signature, batch_ids)
                else:
                    vec = model.encode(texts[start:end], batch_size=BATCH, normalize_embeddings=True,
                        convert_to_numpy=True, show_progress_bar=False).astype(np.float32)
                    vec = save_vectors(part, vec, part_signature, batch_ids, batch_hashes)
                    seconds_each = (time.monotonic()-tick)/len(batch_ids)
                    old = progress.data.get('embedding_seconds_per_item')
                    progress.data['embedding_seconds_per_item'] = .75*old+.25*seconds_each if old else seconds_each
                all_vectors.append(vec)
                progress.data['embedding_completed'] += len(batch_ids)
                progress.data['batch_completed'] = end
                progress.save()
                log('embedding_progress', model=model_id, view=view, completed=end, total=len(ids),
                    cached=cached, seconds=time.monotonic()-tick)
            vectors = save_vectors(output, np.concatenate(all_vectors), signature, ids, hashes)
            inputs_path = directory/f'{view}.inputs.json'
            write(inputs_path, [dict(paper_id=pid,text=text,input_sha256=h,token_length=n)
                for pid,text,h,n in zip(ids,texts,hashes,lengths)])
            metadata = dict(config, vectors=len(ids), dimensions=vectors.shape[1],
                signature=signature, input_sha256=digest(texts), max_actual_tokens=max(lengths),
                path=str(output.relative_to(root)), inputs=str(inputs_path.relative_to(root)),
                file_sha256=hashlib.sha256(output.read_bytes()).hexdigest(), completed_at=now())
            all_meta.setdefault(view, {})[slug] = metadata
            write(root/'embeddings/metadata.json', all_meta)
            for i,row in enumerate(rows):
                row.setdefault('embeddings', {}).setdefault(view, {})[slug] = dict(
                    path=str(output.relative_to(root)), row=i, dimensions=1024,
                    input_sha256=hashes[i], model=model_id, revision=model_path.name)
        del model
        gc.collect()
    if any(set(all_meta[view]) != {m[0] for m in MODELS} for view in views):
        raise ValueError('Every embedding view must have both models')
    return all_meta
