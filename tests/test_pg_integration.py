import os
from pathlib import Path
import tempfile
import unittest
from init_demo import populate
from rag_app.pg_index import PGIndex
from rag_app.security import Actor
from rag_app.store import Store

@unittest.skipUnless(os.getenv("RAG_TEST_PG_DSN"),"Local PostgreSQL/pgvector is not configured")
class PGIntegration(unittest.TestCase):
    def test_vector_sql_acl_and_stale_index(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td)/"pg.sqlite3");populate(store)
            index=PGIndex(os.environ["RAG_TEST_PG_DSN"])
            self.assertGreater(index.sync(store),0)
            alice=Actor("alice","demo",("support",))
            rows=index.retrieve(store,alice,"退款审批")
            self.assertIn("C001",{r["document_id"] for r in rows})
            self.assertFalse(any(r["document_id"].startswith("E") for r in index.retrieve(store,alice,"发布窗口")))
            store.deactivate("C001")
            self.assertEqual(index.retrieve(store,alice,"退款审批"),[])

