import tempfile
import unittest
from pathlib import Path
from rag_app.hybrid import fuse
from rag_app.security import Actor,AccessError,Registry
from rag_app.service import Service
from rag_app.store import Store
from init_demo import populate

class FusionTests(unittest.TestCase):
    def test_rank_fusion_deduplicates_and_ignores_raw_score_scale(self):
        lexical=[{'chunk_id':'a','score':1000},{'chunk_id':'b','score':900}]
        vector=[{'chunk_id':'b','score':.9},{'chunk_id':'c','score':.8}]
        result=fuse(lexical,vector,3)
        self.assertEqual([r['chunk_id'] for r in result],['b','a','c'])
        self.assertEqual(result[0]['channel_ranks'],{'keyword':2,'vector':1})
        self.assertAlmostEqual(result[0]['rrf_score'],1/62+1/61)
    def test_empty_channel_and_ties(self):
        self.assertEqual(fuse([],[],4),[])
        self.assertEqual(len(fuse([{'chunk_id':'a'}],[],4)),1)
        self.assertEqual([r['chunk_id'] for r in fuse([{'chunk_id':'b'}],[{'chunk_id':'a'}],4)],['a','b'])
    def test_unauthorized_vector_candidate_cannot_enter_answer_or_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db');populate(store);alice=Actor('alice','demo',('support',));bob=Actor('bob','demo',('engineering',))
            forbidden=next(r for r in store.authorized_chunks(bob) if r['document_id']=='E001')
            class BadIndex:
                model_id='fake'
                def retrieve(self,*args):return [forbidden]
            with self.assertRaises(AccessError):Service(store,pg_index=BadIndex()).ask('退款',alice,'hybrid')
    def test_api_and_agent_hybrid_use_both_routes(self):
        from fastapi.testclient import TestClient
        from unittest.mock import patch
        from rag_app.api import create_app
        with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{'RAG_CHECKPOINT_DB':str(Path(tmp)/'cp')}):
            store=Store(Path(tmp)/'db');populate(store);alice=Actor('alice','demo',('support',))
            class Index:
                model_id='fake-semantic';calls=0
                def retrieve(self,store,actor,query,k):
                    self.calls+=1
                    return [r for r in store.authorized_chunks(actor) if r['document_id']=='C001']
            index=Index();client=TestClient(create_app(store=store,auth=Registry({'fake':alice}),pg_index=index))
            for route in ['/ask','/agent']:
                response=client.post(route,headers={'Authorization':'Bearer fake'},json={'query':'退款审批','method':'hybrid'})
                self.assertEqual(response.status_code,200)
                output=response.json() if route=='/ask' else response.json()['results'][0]
                self.assertIn('500',output['answer'])
                self.assertTrue(output['retrieval_trace']['keyword_candidates'])
                self.assertTrue(output['retrieval_trace']['vector_candidates'])
                self.assertEqual(output['retrieval_trace']['fusion'],'rrf')
            self.assertEqual(index.calls,2)
