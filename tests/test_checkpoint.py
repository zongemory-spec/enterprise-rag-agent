import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4
from init_demo import populate
from rag_app.checkpoint import Checkpointer
from rag_app.security import Actor, AccessError
from rag_app.store import Store
from rag_app.service import Service
from rag_app.workflow import execute


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "rag.sqlite3")
        populate(self.store)
        self.actor = Actor("alice", "demo", ("support",))
        self.cp = Checkpointer(self.root / "checkpoints.sqlite3")
        self.service = Service(self.store)

    def tearDown(self): self.temp.cleanup()

    def test_partial_step_survives_failure_and_resume(self):
        class Failing:
            def __init__(self): self.n=0
            def next(self, messages):
                self.n+=1
                if self.n==2: raise RuntimeError("simulated shutdown")
                return {"name":"get_ticket_status","arguments":{"ticket_id":"T1001"}}
        with self.assertRaises(RuntimeError):
            execute(self.service,self.cp,"check ticket",self.actor,Failing(),workflow_id="same")
        class Finish:
            def next(inner,messages):
                self.assertEqual(len(messages),4)
                return None
        restored=Checkpointer(self.root / "checkpoints.sqlite3")
        result=execute(self.service,restored,"check ticket",self.actor,Finish(),workflow_id="same")
        self.assertEqual(result["tool_calls"],1)
        self.assertEqual(result["results"][0]["ticket_id"],"T1001")

    def test_fresh_process_reads_persisted_state(self):
        state,lease=self.cp.acquire(self.actor,"restart",{"proof":123})
        self.cp.save(self.actor,"restart",lease,state,release=True)
        code="""import sys,json
from rag_app.checkpoint import Checkpointer
from rag_app.security import Actor
c=Checkpointer(sys.argv[1]);a=Actor('alice','demo',('support',))
s,l=c.acquire(a,'restart',{});c.save(a,'restart',l,s,release=True)
print(json.dumps(s))
"""
        result=subprocess.run([sys.executable,"-c",code,str(self.cp.path)],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(result.stdout),{"proof":123})

    def test_concurrent_resume_and_scope(self):
        state,lease=self.cp.acquire(self.actor,"same",{"private":1})
        with self.assertRaises(AccessError):self.cp.acquire(self.actor,"same",{})
        other=Actor("alice","other",("support",))
        separate,token=self.cp.acquire(other,"same",{})
        self.assertEqual(separate,{})
        self.cp.save(other,"same",token,separate,release=True)
        with self.assertRaises(AccessError):self.cp.save(self.actor,"same","wrong",{})
        self.cp.save(self.actor,"same",lease,state,release=True)

    def test_resume_rejects_revoked_data_and_changed_query(self):
        execute(self.service,self.cp,"退款审批",self.actor,workflow_id="query")
        with self.assertRaises(AccessError):execute(self.service,self.cp,"different",self.actor,workflow_id="query")
        self.store.deactivate("C001")
        with self.assertRaises(AccessError):execute(self.service,self.cp,"退款审批",self.actor,workflow_id="query")

    @unittest.skipUnless(os.getenv("RAG_TEST_PG_DSN"),"PostgreSQL test DSN required")
    def test_postgresql_checkpoint_persists(self):
        from rag_app.postgres_store import PostgresStore
        store=PostgresStore(os.environ["RAG_TEST_PG_DSN"],"checkpoint_"+uuid4().hex)
        cp=Checkpointer(pg_store=store)
        state,lease=cp.acquire(self.actor,"flow",{"step":2})
        cp.save(self.actor,"flow",lease,state,release=True)
        again=Checkpointer(pg_store=store)
        state,lease=again.acquire(self.actor,"flow",{})
        self.assertEqual(state,{"step":2})
        again.save(self.actor,"flow",lease,state,release=True)
