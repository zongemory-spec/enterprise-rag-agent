import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from rag_app.request_budget import PersistentBudget
from rag_app.embedding import HTTPEmbedding
from rag_app.security import AccessError,Actor

class BudgetTests(unittest.TestCase):
    def test_budget_survives_restart_and_separates_kinds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'budget';a=PersistentBudget(path,{'embedding':1,'chat':1});a('embedding')
            b=PersistentBudget(path,{'embedding':1,'chat':1})
            with self.assertRaises(AccessError):b('embedding')
            b('chat');self.assertEqual(b.status()['chat']['used'],1)
    def test_space_identity_includes_model_dimension_and_endpoint(self):
        def model(url='https://one',name='model',dim=1024):return HTTPEmbedding(url,'fake',name,dim).model_id
        self.assertEqual(model(),model())
        for identity in [model(url='https://two'),model(name='other'),model(dim=512)]:self.assertNotEqual(model(),identity)

@unittest.skipUnless(os.getenv('RAG_TEST_PG_DSN'),'PostgreSQL test DSN required')
class SemanticPGTests(unittest.TestCase):
    def test_model_change_and_stale_index_fail_before_query_embedding(self):
        from rag_app.postgres_store import PostgresStore
        from rag_app.pg_native_index import NativePGIndex
        from init_demo import populate
        store=PostgresStore(os.environ['RAG_TEST_PG_DSN'],'semantic_test_'+uuid4().hex);populate(store)
        class Fake:
            model_id='test-semantic-space';calls=0
            def embed(self,texts):self.calls+=1;return [[1.,0.] for _ in texts]
        fake=Fake();index=NativePGIndex(store,fake);actor=Actor('alice','demo',('support',))
        with self.assertRaises(AccessError):index.retrieve(store,actor,'退款')
        self.assertEqual(fake.calls,0)
        index.sync();self.assertTrue(index.status()['ready'])
        result=index.retrieve(store,actor,'退款',100)
        self.assertFalse(any(r['document_id'].startswith(('E','O')) for r in result))
        before=fake.calls;fake.model_id='new-space'
        changed=NativePGIndex(store,fake)
        with self.assertRaises(AccessError):changed.retrieve(store,actor,'退款')
        self.assertEqual(fake.calls,before)
        store.deactivate('C001')
        with self.assertRaises(AccessError):index.retrieve(store,actor,'退款')
