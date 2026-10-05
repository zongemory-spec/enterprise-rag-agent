from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from init_demo import populate
from rag_app.api import create_app
from rag_app.security import Actor,Registry
from rag_app.store import Store

class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/"api.sqlite3");populate(self.store)
        self.auth=Registry({"alice-demo-token":Actor("alice","demo",("support",)),"bob-demo-token":Actor("bob","demo",("engineering",))})
        self.client=TestClient(create_app(self.store,self.auth));self.addCleanup(self.client.close)
    def headers(self,user="alice"):return {"Authorization":"Bearer "+user+"-demo-token"}
    def test_auth_and_health(self):
        self.assertEqual(self.client.get("/health").status_code,200)
        self.assertEqual(self.client.post("/ask",json={"query":"差旅报销"}).status_code,401)
    def test_no_identity_or_group_override(self):
        for key,value in [("actor","bob"),("groups",["engineering"]),("tenant_id","other")]:
            self.assertEqual(self.client.post("/ask",headers=self.headers(),json={"query":"差旅报销",key:value}).status_code,422)
    def test_validation_no_sensitive_echo(self):
        r=self.client.post("/ask",headers=self.headers(),json={"query":"sk-test-secret","top_k":False})
        self.assertEqual(r.status_code,422);self.assertNotIn("sk-test-secret",r.text)
    def test_ask_citation_and_run(self):
        r=self.client.post("/ask",headers=self.headers(),json={"query":"退款审批"});self.assertEqual(r.status_code,200)
        self.assertIn("X-Request-ID",r.headers);data=r.json()
        self.assertEqual(self.client.get(data["citations"][0]["url"],headers=self.headers()).status_code,200)
        self.assertEqual(self.client.get(data["citations"][0]["url"],headers=self.headers("bob")).status_code,404)
        self.assertEqual(self.client.get("/runs/"+data["run_id"],headers=self.headers("bob")).status_code,403)
    def test_pgvector_unconfigured(self):
        r=self.client.post("/ask",headers=self.headers(),json={"query":"差旅报销","method":"pgvector"})
        self.assertEqual(r.status_code,503)
    def test_ticket(self):
        r=self.client.post("/agent",headers=self.headers(),json={"query":"/ticket T1001"})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()["tool_calls"],1)
    def test_ui_served_without_credentials(self):
        r=self.client.get("/")
        self.assertEqual(r.status_code,200);self.assertNotIn("alice-demo-token",r.text)

