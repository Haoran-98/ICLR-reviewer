"""Opt-in real PostgreSQL migration/contract tests in a throwaway database only."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from argparse import Namespace

import numpy as np
import psycopg
from psycopg import sql

REPO=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('s4',REPO/'scripts/s4_taxonomy_pipeline.py')
s4=importlib.util.module_from_spec(spec);spec.loader.exec_module(s4)
sys.path.insert(0,str(REPO/'scripts'))
import s4_llm_taxonomy as llm4
import s4_crowd_fusion as fusion


@unittest.skipUnless(os.environ.get('S4_DATABASE_TEST')=='1','set S4_DATABASE_TEST=1 for temporary database tests')
class DatabaseTests(unittest.TestCase):
    def test_llm4_persist_six_fields_and_parent_closure_idempotently(self):
        with psycopg.connect(self.url,autocommit=True) as c:
            run=c.execute("INSERT INTO raw.ingest_run(status,source_root) VALUES('success','llm4_fixture') RETURNING ingest_run_id").fetchone()[0]
            source=c.execute("""INSERT INTO raw.source_record(ingest_run_id,source_kind,source_path,
                conference_year,sha256,byte_size,raw_payload) VALUES(%s,'paper_metadata','llm4_fixture',2024,%s,0,'{}')
                RETURNING source_record_id""",(run,'f'*64)).fetchone()[0]
            venue=c.execute("INSERT INTO core.venue(name,year) VALUES('llm4_fixture',2024) RETURNING venue_id").fetchone()[0]
            ids=[c.execute("""INSERT INTO core.paper(venue_id,openreview_id,forum_id,track,source_record_id)
                VALUES(%s,%s,%s,'main',%s) RETURNING paper_id""",(venue,'v4_'+str(i),'v4_'+str(i),source)).fetchone()[0] for i in range(2)]
            c.execute("""INSERT INTO semantic.taxonomy_version(taxonomy_version,status,profile_version,split_manifest_hash,config_hash)
                VALUES(%s,'experimental','fixture',%s,%s)""",(llm4.VERSION,'a'*64,'b'*64))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            args=Namespace(root=root,database_url=self.url)
            papers=[{'paper_id':pid,'year':2024,'raw_input_hash':'c'*64} for pid in ids]
            llm4.write(root/'manifest.json',{'version':llm4.VERSION,'papers':papers})
            llm4.write(root/'embedding_stats.json',{'revision':llm4.REVISION})
            vectors=np.zeros((2,6,1024),dtype='float32')
            vectors[:,:,0]=1
            np.savez_compressed(root/'section_vectors.npz',vectors=vectors,masks=np.ones((2,6),dtype=bool),paper_ids=np.array(ids))
            for pid in ids:
                llm4.write(root/'sections'/f'{pid}.json',{field:{'content_hash':llm4.digest(field)} for field in llm4.FIELDS})
            nodes={key:{'level':level,'name':key,'definition':'Definition','facet':'task','parents':parents,
                        'aliases':[key],'members':[{'paper_id':pid,'provider':'kimi','evidence':[]} for pid in ids]}
                   for key,level,parents in [('root',1,[]),('child',2,['root']),('orphan',3,[])]}
            llm4.write(root/'taxonomy_E1R1.json',{'nodes':nodes,'active_nodes':['root','child'],
                       'assignments':[{'paper_id':pid,'node_id':key,'score':.95} for pid in ids for key in ('root','child')]})
            fusion.persist(args)
            first=llm4.read(root/'persistence.json')
            fusion.persist(args)
            self.assertEqual(first,llm4.read(root/'persistence.json'))
            self.assertEqual(first,{'taxonomy_node':3,'taxonomy_edge':1,'paper_taxonomy_assignment':4,'embedding':12})

    @classmethod
    def setUpClass(cls):
        cls.admin_url='postgresql://yhr@127.0.0.1:55432/postgres'
        cls.name='s4_contract_test_'+uuid.uuid4().hex[:12]
        with psycopg.connect(cls.admin_url,autocommit=True) as c:
            c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        cls.url='postgresql://yhr@127.0.0.1:55432/'+cls.name
        cls.env={**os.environ,'ICLR_DATABASE_URL':cls.url.replace('postgresql://','postgresql+psycopg://')}
        try:
            cls.migrate('upgrade','head')
            cls.migrate('downgrade','0005')
            cls.migrate('upgrade','head')
        except Exception:
            cls.tearDownClass();raise

    @classmethod
    def migrate(cls,*args):
        subprocess.run(['python3','-m','alembic',*args],cwd=REPO,env=cls.env,check=True,capture_output=True,text=True)

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(cls.admin_url,autocommit=True) as c:
            c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(cls.name)))

    def test_contract_and_persist_idempotence(self):
        with psycopg.connect(self.url,autocommit=True) as c:
            run=c.execute("INSERT INTO raw.ingest_run(status,source_root) VALUES('success','fixture') RETURNING ingest_run_id").fetchone()[0]
            source=c.execute("""INSERT INTO raw.source_record(ingest_run_id,source_kind,source_path,
                conference_year,sha256,byte_size,raw_payload) VALUES(%s,'paper_metadata','fixture',2024,%s,0,'{}')
                RETURNING source_record_id""",(run,'a'*64)).fetchone()[0]
            venue=c.execute("INSERT INTO core.venue(name,year) VALUES('fixture',2024) RETURNING venue_id").fetchone()[0]
            ids=[c.execute("""INSERT INTO core.paper(venue_id,openreview_id,forum_id,track,source_record_id)
                VALUES(%s,%s,%s,'main',%s) RETURNING paper_id""",(venue,str(i),str(i),source)).fetchone()[0] for i in range(2)]
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);args=Namespace(root=root,database_url=self.url,seed=1701)
            rows=[{'paper_id':i,'year':2024,'canonical_key':'a','split':split,'group_key':str(i)} for i,split in zip(ids,('train','test'))]
            s4.write(root/'manifest.json',{'version':'taxonomy_smoke_v0','papers':rows,'manifest_hash':s4.digest(rows)})
            s4.write(root/'anchors.json',[{'stable_key':'a','name':'A','years':[2024],'level':1,'facet_type':'mixed'}])
            child={'stable_key':'a/L2/b','parent':'a','name':'B','definition':'B','level':2,'facet_type':'task',
                   'members':[ids[0]],'review_status':'accepted'}
            clusters={'nodes':[child]}
            s4.write(root/'clusters.json',clusters)
            s4.write(root/'embedding_stats.json',{'spec':{'model_name':'fixture','model_revision':'fixed'}})
            s4.write(root/'candidate_lock.json',{'nodes_hash':s4.digest(clusters),
                'manifest_hash':s4.digest(rows),'assignment_config':s4.ASSIGNMENT_CONFIG,
                'embedding_spec_hash':s4.digest(s4.read(root/'embedding_stats.json')['spec'])})
            v=np.zeros((1,1024),dtype='float32');v[0,0]=1
            for i,split in zip(ids,('train','test')):
                suffix='_test' if split=='test' else ''
                s4.write(root/f'vector_ids{suffix}.json',[i]);np.save(root/f'vectors{suffix}.npy',v)
                s4.write(root/f'input_hashes{suffix}.json',{str(i):{'F1':'b'*64}})
                s4.write(root/f'assignments{suffix}.json',[{'paper_id':i,'stable_key':key,'score':.8,'score_type':'similarity',
                    'rank':rank,'is_primary':rank==1,'source':'fixture','evidence':[],'split':split}
                    for rank,key in enumerate(('a','a/L2/b'),1)])
            s4.persist(args);first=s4.read(root/'persistence.json')['counts']
            s4.persist(args);self.assertEqual(first,s4.read(root/'persistence.json')['counts'])
            self.assertEqual(first,{'nodes':2,'edges':1,'assignments':4,'embeddings':2})
        with psycopg.connect(self.url,autocommit=True) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM semantic.frozen_taxonomy_node').fetchone()[0],0)
            nodes=c.execute("SELECT taxonomy_node_id,level FROM semantic.taxonomy_node ORDER BY level").fetchall()
            parent,child=nodes[0][0],nodes[1][0]
            with self.assertRaises(psycopg.errors.RaiseException):
                c.execute("""INSERT INTO semantic.taxonomy_edge(taxonomy_version,source_node_id,target_node_id,
                    relation_type) VALUES('taxonomy_smoke_v0',%s,%s,'parent_of')""",(child,parent))
            with self.assertRaises(psycopg.errors.RaiseException):
                c.execute("DELETE FROM semantic.paper_taxonomy_assignment WHERE paper_id=%s AND taxonomy_node_id=%s",(ids[0],parent))
            with self.assertRaises(psycopg.errors.RaiseException):
                c.execute("DELETE FROM semantic.taxonomy_edge WHERE source_node_id=%s AND target_node_id=%s",(parent,child))
            c.execute("""INSERT INTO semantic.taxonomy_version(taxonomy_version,status,profile_version,
                split_manifest_hash,config_hash) VALUES('another','experimental','fixture',%s,%s)""",('c'*64,'d'*64))
            foreign=c.execute("""INSERT INTO semantic.taxonomy_node(taxonomy_version,level,name)
                VALUES('another',2,'other') RETURNING taxonomy_node_id""").fetchone()[0]
            with self.assertRaises(psycopg.errors.RaiseException):
                c.execute("""INSERT INTO semantic.taxonomy_edge(taxonomy_version,source_node_id,target_node_id,
                    relation_type) VALUES('taxonomy_smoke_v0',%s,%s,'overlaps_with')""",(parent,foreign))
            with self.assertRaises(psycopg.errors.RaiseException):
                c.execute("UPDATE semantic.taxonomy_version SET status='frozen',frozen_at=now() WHERE taxonomy_version='taxonomy_smoke_v0'")
            # Freeze the fixture using a real snapshot and assert all stored artifacts are immutable.
            snapshot=c.execute("""INSERT INTO ops.dataset_snapshot(name,schema_version,table_counts,
                object_manifest_sha256,validation_report) VALUES('s4_fixture','0008','{}',%s,'{}')
                RETURNING dataset_snapshot_id""",('e'*64,)).fetchone()[0]
            c.execute("""UPDATE semantic.taxonomy_version SET dataset_snapshot_id=%s,
                metadata='{"s3_frozen":true}',status='frozen',frozen_at=now() WHERE taxonomy_version='another'""",(snapshot,))
            self.assertEqual(c.execute('SELECT count(*) FROM semantic.frozen_taxonomy_node').fetchone()[0],1)
            for statement,params in [
                ("UPDATE semantic.taxonomy_node SET definition='changed' WHERE taxonomy_node_id=%s",(foreign,)),
                ("UPDATE semantic.taxonomy_node SET taxonomy_version='taxonomy_smoke_v0' WHERE taxonomy_node_id=%s",(foreign,)),
                ("DELETE FROM semantic.taxonomy_node WHERE taxonomy_node_id=%s",(foreign,)),
                ("UPDATE semantic.taxonomy_version SET status='experimental' WHERE taxonomy_version='another'",()),
            ]:
                with self.assertRaises(psycopg.errors.RaiseException):
                    c.execute(statement,params)


if __name__=='__main__':unittest.main()
