import os,unittest,uuid
from concurrent.futures import ThreadPoolExecutor
from init_demo import populate
from rag_app.postgres_store import PostgresStore
from rag_app.pg_native_index import NativePGIndex
from rag_app.security import Actor,AccessError
@unittest.skipUnless(os.getenv("RAG_TEST_PG_DSN"),"PostgreSQL test DSN required")
class PGIntegration(unittest.TestCase):
    def setUp(self):
        self.store=PostgresStore(os.environ["RAG_TEST_PG_DSN"],"test_"+uuid.uuid4().hex)
        populate(self.store)
        self.alice=Actor("alice","demo",("support",))
    def test_native_vector_acl_and_generation(self):
        index=NativePGIndex(self.store)
        self.assertGreater(index.sync(),0)
        self.assertIn("C001",{r["document_id"] for r in index.retrieve(self.store,self.alice,"退款审批")})
        self.assertFalse(any(r["document_id"].startswith("E") for r in index.retrieve(self.store,self.alice,"发布窗口")))
        self.store.deactivate("C001")
        with self.assertRaises(AccessError):index.retrieve(self.store,self.alice,"退款审批")
        index.sync()
        self.assertFalse(any(r["document_id"]=="C001" for r in index.retrieve(self.store,self.alice,"退款审批")))
    def test_history_revocation_and_tenant(self):
        row=next(r for r in self.store.authorized_chunks(self.alice) if r["document_id"]=="C001")
        self.store.save_run("run",self.alice,[row["chunk_id"]],{})
        self.store.deactivate("C001")
        self.assertEqual(self.store.run("run",self.alice)["redacted_chunks"],1)
        with self.assertRaises(AccessError):self.store.citation(row["chunk_id"],self.alice)
        with self.assertRaises(AccessError):self.store.run("run",Actor("alice","other",("support",)))
        with self.assertRaises(AccessError):self.store.ticket("T1002",self.alice)
        self.assertEqual(self.store.ticket("T1001",self.alice)["status"],"open")
    def test_incremental_index_reuses_vectors_and_shared_application_state(self):
        from rag_app.application_state import ApplicationState
        from rag_app.document_management import Documents
        index=NativePGIndex(self.store);index.sync()
        self.assertEqual(index.sync(),0)
        state=ApplicationState(self.store);documents=Documents(self.store,state,index)
        uploaded=documents.upload(self.alice,'new.md',b'New upload policy: deadline is 12 days.','New upload policy',[])
        self.assertFalse(index.status()['ready'])
        index.sync()
        self.assertEqual(index.last_sync['embedded_chunks'],1)
        self.assertGreater(index.last_sync['retained_chunks'],0)
        self.assertTrue(index.status()['ready'])
        cid=state.create_conversation(self.alice)['conversation_id']
        self.assertEqual(state.conversation(self.alice,cid)['version'],0)
        documents.delete(self.alice,uploaded['document_id'],1)
        self.assertEqual(index.sync(),0)
        self.assertEqual(index.last_sync['removed_chunks'],1)

    def test_concurrent_upsert_and_rollback(self):
        doc={"document_id":"NEW","version":1,"title":"Test","source":"synthetic","tenant_id":"demo","owner":"alice","allowed_groups":["support"],"created_at":"2026-10-01"}
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:self.store.upsert(doc,"test content"),range(2)))
        self.assertEqual(sorted(results),[False,True])
        version=self.store.index_version
        with self.assertRaises(Exception):self.store.upsert(dict(doc,version=2),"changed",[("location",None)])
        self.assertEqual(self.store.index_version,version)
        self.assertEqual([r["version"] for r in self.store.authorized_chunks(self.alice) if r["document_id"]=="NEW"],[1])
        with self.assertRaises(ValueError):self.store.upsert(dict(doc,version=2,tenant_id="other"),"bad")
    def test_native_api_and_restart(self):
        from fastapi.testclient import TestClient
        from rag_app.api import create_app
        from rag_app.security import Registry
        import inspect
        class Auth:
            def authenticate(inner,value):return self.alice
        index=NativePGIndex(self.store);index.sync()
        with TestClient(create_app(self.store,Auth(),pg_index=index)) as client:
            r=client.post("/ask",json={"query":"退款审批","method":"pgvector"})
            self.assertEqual(r.status_code,200,r.text)
        again=PostgresStore(self.store.dsn,self.store.schema)
        self.assertEqual(again.index_version,self.store.index_version)
        with again.connect() as c:
            self.assertGreater(c.execute("SELECT count(*) AS n FROM audit").fetchone()["n"],0)

    def test_sqlite_migration_is_read_only_and_preserves_revocation(self):
        import tempfile,hashlib
        from pathlib import Path
        from rag_app.store import Store
        from migrate_sqlite import migrate
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"old.sqlite3"
            old=Store(path);populate(old);old.deactivate("C001")
            before=hashlib.sha256(path.read_bytes()).hexdigest()
            target=PostgresStore(self.store.dsn,"migration_"+uuid.uuid4().hex)
            counts=migrate(path,target)
            self.assertEqual(counts["documents"],24)
            self.assertEqual(target.index_version,old.index_version)
            self.assertFalse(any(r["document_id"]=="C001" for r in target.authorized_chunks(self.alice)))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
            with self.assertRaises(ValueError):migrate(path,target)
