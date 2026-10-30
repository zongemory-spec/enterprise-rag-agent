import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from check_evaluation import check_report
from init_demo import populate
from rag_app.api import create_app
from rag_app.application_state import ApplicationState
from rag_app.checkpoint import Checkpointer
from rag_app.corrective import retrieve_with_correction
from rag_app.retention import Retention
from rag_app.sections import split_sections,expand_sections
from rag_app.security import Actor,AccessError,Registry
from rag_app.service import Service
from rag_app.store import Store

ROOT=Path(__file__).parents[1]


class CorrectiveTests(unittest.TestCase):
    def test_useful_alias_retries_once_and_records_both_rankings(self):
        seen=[]
        def retrieve(query):
            seen.append(query)
            return {'evidence_check':{'status':'accepted' if query=='报销' else 'insufficient'},
                    'retrieved_chunk_ids':['supported'] if query=='报销' else [],'retrieval_trace':{}}
        result=retrieve_with_correction('报账',retrieve)
        self.assertEqual(seen,['报账','报销'])
        self.assertEqual(result['retrieval_trace']['correction']['outcome'],'supported')
        self.assertEqual(len(result['retrieval_trace']['correction']['attempts']),2)

    def test_no_repeated_request_without_rewrite_and_no_provider_error_fallback(self):
        seen=[]
        def retrieve(query):
            seen.append(query)
            return {'evidence_check':{'status':'insufficient'},'retrieved_chunk_ids':[],'retrieval_trace':{}}
        retrieve_with_correction('unlisted subject',retrieve)
        self.assertEqual(len(seen),1)
        def broken(query):raise AccessError('model_timeout',504)
        with self.assertRaises(AccessError):retrieve_with_correction('报账',broken)


class PersonalDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=Store(self.root/'db');populate(self.store)
        self.actor=Actor('alice','demo',('support',));self.bob=Actor('bob','demo',('engineering',))
        self.state=ApplicationState(self.store);self.cp=Checkpointer(self.root/'cp')
        env=patch.dict('os.environ',{'RAG_CHECKPOINT_DB':str(self.root/'cp')});env.start();self.addCleanup(env.stop)
        self.app=create_app(store=self.store,auth=Registry({'alice':self.actor,'bob':self.bob}))
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.headers={'Authorization':'Bearer alice'}

    def document(self,did,version,text,owner='alice'):
        meta={'document_id':did,'version':version,'title':'Orion travel guide','source':'showcase',
              'tenant_id':'demo','owner':owner,'allowed_groups':[],'created_at':'2026-10-01'}
        self.store.upsert(meta,text,split_sections(text,140))

    def test_actual_service_alias_and_permission_scope(self):
        answer=Service(self.store).ask('报账',self.actor,'bm25')
        self.assertFalse(answer['refused'])
        self.assertEqual(len(answer['retrieval_trace']['correction']['attempts']),2)
        denied=Service(self.store).ask('退款报账',self.bob,'bm25')
        self.assertFalse(any(c['document_id'].startswith('C') for c in denied['citations']))

    def test_same_section_expansion_preserves_child_citations_and_excludes_other_sections(self):
        text='# Orion guide\n## Cabin approval\n'+('Cabin allowance details. '*20)+'\nManager approval is required.\n## Passwords\nUnrelated password policy.'
        self.document('SECTIONS',1,text)
        chunks=[c for c in self.store.authorized_chunks(self.actor) if c['document_id']=='SECTIONS']
        hit=next(c for c in chunks if 'Cabin allowance' in c['text'])
        expanded,added=expand_sections(self.store,self.actor,[hit],max_chars=2000)
        self.assertTrue(added)
        self.assertFalse(any('Unrelated password' in c['text'] for c in expanded))
        self.assertEqual(expanded[0]['chunk_id'],hit['chunk_id'])
        self.assertTrue(all('section 2:' in c['location'] for c in expanded))

    def test_ambiguous_followup_returns_accessible_choices(self):
        first=self.client.post('/chat',headers=self.headers,json={'query':'差旅报销和入职材料分别有什么要求？'}).json()
        reply=self.client.post('/chat',headers=self.headers,json={'query':'那具体呢？','conversation_id':first['conversation_id']}).json()
        self.assertTrue(reply['refused']);self.assertEqual(reply['refusal_reason'],'ambiguous_followup')
        self.assertGreaterEqual(len(reply['clarification']['choices']),2)
        self.store.deactivate('S001')
        history=self.client.get('/conversations/'+first['conversation_id'],headers=self.headers).json()
        self.assertTrue(history['turns'][-1]['redacted'])

    def test_cleanup_preview_apply_and_cross_user_scope(self):
        own=self.client.post('/chat',headers=self.headers,json={'query':'退款审批'}).json()
        other=self.app.state.conversations.ask(self.bob,'发布窗口')
        preview=self.client.post('/privacy/cleanup',headers=self.headers,json={'all_personal_records':True}).json()
        self.assertTrue(preview['dry_run']);self.assertEqual(preview['counts']['conversations'],1)
        self.assertEqual(len(self.state.conversations(self.actor)),1)
        applied=self.client.post('/privacy/cleanup',headers=self.headers,json={'all_personal_records':True,'dry_run':False})
        self.assertEqual(applied.status_code,200,applied.text)
        self.assertEqual(self.state.conversations(self.actor),[])
        self.assertEqual(len(self.state.conversations(self.bob)),1)
        self.assertTrue(self.store.authorized_chunks(self.actor))
        self.assertEqual(self.client.get('/runs/'+own['run_id'],headers=self.headers).status_code,404)
        self.assertEqual(self.client.get('/conversations/'+other['conversation_id'],headers={'Authorization':'Bearer bob'}).status_code,200)

    def test_retention_keeps_recently_active_old_conversation(self):
        reply=self.app.state.conversations.ask(self.actor,'退款审批')
        with self.store.connect() as c:
            c.execute("UPDATE app_conversations SET created='2000-01-01T00:00:00+00:00' WHERE id=?",(reply['conversation_id'],))
        result=Retention(self.state).cleanup(self.actor,days=30,dry_run=False)
        self.assertEqual(result['counts']['conversations'],0)
        self.assertEqual(len(self.state.conversations(self.actor)),1)

    def test_active_jobs_and_leases_are_preserved(self):
        jid=self.state.create_job(self.actor,'S001')
        state,lease=self.cp.acquire(self.actor,'busy',{})
        result=Retention(self.state,self.cp).cleanup(self.actor,all_records=True,dry_run=False)
        self.assertEqual(result['counts']['active_jobs_kept'],1)
        self.assertEqual(result['checkpoints']['active_kept'],1)
        self.assertEqual(self.state.job(self.actor,jid)['status'],'queued')
        self.cp.save(self.actor,'busy',lease,state,release=True)

    def test_only_owned_inactive_versions_are_pruned(self):
        for version in range(1,4):self.document('OWN',version,'Own policy version '+str(version))
        for version in range(1,4):self.document('OTHER',version,'Other policy version '+str(version),owner='bob')
        result=Retention(self.state).cleanup(self.actor,prune_versions=True,keep_versions=1,dry_run=False)
        self.assertEqual(result['counts']['inactive_document_versions'],2)
        with self.store.connect() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM documents WHERE document_id='OWN'").fetchone()[0],1)
            self.assertEqual(c.execute("SELECT count(*) FROM documents WHERE document_id='OTHER'").fetchone()[0],3)
        self.assertTrue(any(c['document_id']=='OWN' for c in self.store.authorized_chunks(self.actor)))

    def test_personal_export_and_cleanup_reject_identity_override(self):
        self.client.post('/chat',headers=self.headers,json={'query':'退款审批'})
        export=self.client.get('/privacy/export',headers=self.headers)
        self.assertEqual(export.status_code,200);self.assertEqual(export.json()['format'],'personal-records-v1')
        self.assertNotIn('Bearer',export.text)
        self.assertEqual(self.client.post('/privacy/cleanup',headers=self.headers,json={'actor':'bob'}).status_code,422)
        self.assertEqual(self.client.post('/privacy/cleanup',json={}).status_code,401)


class SectionAndGateTests(unittest.TestCase):
    def test_heading_boundaries_and_original_line_numbers(self):
        chunks=split_sections('# Guide\nintro\n## Expenses\nexpense detail\n## Equipment\ndevice detail')
        self.assertEqual(len(chunks),3)
        self.assertIn('lines 3-4',chunks[1][0]);self.assertIn('Expenses',chunks[1][0])
        self.assertNotIn('device detail',chunks[1][1])

    def test_gate_rejects_regressions_missing_metrics_nan_and_leaks(self):
        config=json.loads((ROOT/'evaluation_gate.json').read_text(encoding='utf-8'))
        baseline=json.loads((ROOT/'reports/v4.1-dev.json').read_text(encoding='utf-8'))
        self.assertTrue(check_report(baseline,config,baseline)['passed'])
        for key,value in [('recall_at_1_macro',.1),('false_refusal_rate',.8),('recall_at_4_macro',float('nan'))]:
            report=copy.deepcopy(baseline)
            next(r for r in report['results'] if r['method']=='bm25')['metrics'][key]=value
            self.assertFalse(check_report(report,config,baseline)['passed'])
        report=copy.deepcopy(baseline)
        next(r for r in report['results'] if r['method']=='bm25')['metrics']['leak_events']['output_leaks']=1
        self.assertFalse(check_report(report,config,baseline)['passed'])
        report=copy.deepcopy(baseline);report['dataset_sha256']='different'
        self.assertFalse(check_report(report,config,baseline)['passed'])
