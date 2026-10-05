import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from init_demo import populate
from rag_app.store import Store
from rag_app.service import Service
from rag_app.security import Actor,AccessError
from rag_app.checkpoint import Checkpointer
from rag_app.planner import HTTPPlanner
from rag_app.synthesis import ModelBudget,validate_answer
from rag_app.workflow import execute

class UpgradeTests(unittest.TestCase):
    def test_api_mode_and_agent_answer(self):
        from fastapi.testclient import TestClient
        from rag_app.api import create_app
        from rag_app.security import Registry
        import os
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,{'RAG_CHECKPOINT_DB':str(Path(temp)/'cp')}):
            store=Store(Path(temp)/'db');populate(store)
            client=TestClient(create_app(store=store,auth=Registry({'fake-token':Actor('alice','demo',('support',))})))
            self.assertEqual(client.get('/capabilities').json()['planner'],'offline-script')
            result=client.post('/agent',headers={'Authorization':'Bearer fake-token'},json={'query':'退款审批'})
            self.assertEqual(result.status_code,200)
            self.assertIn('500',result.json()['answer'])
            self.assertTrue(result.json()['citations'])
    def test_native_tool_call_and_history(self):
        def handler(request):
            body=json.loads(request.content)
            self.assertEqual(body['messages'][-1]['role'],'tool')
            self.assertEqual(len(body['tools']),2)
            return httpx.Response(200,json={'choices':[{'message':{'tool_calls':[{'function':{'name':'search_knowledge','arguments':'{"query":"退款审批"}'}}]}}]})
        original=httpx.Client
        with patch('rag_app.planner.httpx.Client',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
            call=HTTPPlanner('https://invalid','fake','fake').next([{'role':'user','content':'question'},{'role':'assistant','content':'{"name":"get_ticket_status","arguments":{"ticket_id":"T1001"}}'},{'role':'user','content':'UNTRUSTED_TOOL_DATA: {}'}])
            self.assertEqual(call['name'],'search_knowledge')
    def test_budget_and_forged_reference(self):
        budget=ModelBudget(1);budget('chat')
        with self.assertRaises(AccessError):budget('chat')
        with self.assertRaises(AccessError):validate_answer([{'text':'invented','evidence_ids':['999']}],[{'id':'1','text':'fact'}])
    def test_multistep_synthesis_resume_and_revoke(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'db.sqlite3');populate(store)
            cp=Checkpointer(Path(temp)/'cp.sqlite3');actor=Actor('alice','demo',('support',));service=Service(store)
            class Planner:
                def __init__(self):self.calls=iter([{'name':'get_ticket_status','arguments':{'ticket_id':'T1001'}},{'name':'search_knowledge','arguments':{'query':'退款审批'}},None])
                def next(self,messages):return next(self.calls)
            class Synth:
                model='fake';count=0
                def generate(self,query,rows):
                    self.count+=1
                    return [{'text':row['text'],'evidence_ids':[row['id']]} for row in rows]
            synth=Synth()
            result=execute(service,cp,'查工单和退款政策',actor,Planner(),workflow_id='multi',synthesizer=synth)
            self.assertEqual(result['tool_calls'],2);self.assertIn('500',result['answer']);self.assertIn('open',result['answer'])
            execute(service,cp,'查工单和退款政策',actor,Planner(),workflow_id='multi',synthesizer=synth)
            self.assertEqual(synth.count,1)
            store.deactivate('C001')
            with self.assertRaises(AccessError):execute(service,cp,'查工单和退款政策',actor,workflow_id='multi',synthesizer=synth)
    def test_revocation_during_synthesis(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'db');populate(store);cp=Checkpointer(Path(temp)/'cp')
            class Synth:
                def generate(self,q,rows):
                    store.deactivate('C001')
                    return [{'text':rows[0]['text'],'evidence_ids':[rows[0]['id']]}]
            with self.assertRaises(AccessError):execute(Service(store),cp,'退款审批',Actor('alice','demo',('support',)),synthesizer=Synth())
