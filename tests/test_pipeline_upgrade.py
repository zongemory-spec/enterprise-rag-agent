import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import httpx
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from rag_app.api import create_app
from rag_app.bm25 import rank_bm25, tokens
from rag_app.checkpoint import Checkpointer
from rag_app.langchain_components import AuthorizedRetriever, authorized_tools
from rag_app.langchain_planner import LangChainPlanner
from rag_app.metrics import retrieval_metrics
from rag_app.reranking import HTTPReranker, CrossEncoderReranker, apply_scores, configured_reranker
from rag_app.security import Actor, AccessError, Registry
from rag_app.service import Service
from rag_app.store import Store
from rag_app.tracing import trace_scope, span, LangfuseTracer
from rag_app.workflow import execute
from init_demo import populate


class MetricsTests(unittest.TestCase):
    def test_recall_1_is_not_hit_1_on_multi_document_questions(self):
        m = retrieval_metrics(['b', 'a'], ['A', 'B'], {'a': {'document_id': 'A'}, 'b': {'document_id': 'B'}})
        self.assertEqual(m, {'recall_at_1': .5, 'hit_at_1': 1., 'recall_at_4': 1., 'mrr_at_4': 1.})

    def test_order_duplicates_missing_and_refusals(self):
        rows = {'a': {'document_id': 'A'}, 'b': {'document_id': 'B'}}
        m = retrieval_metrics(['b', 'b', 'a'], ['A'], rows)
        self.assertEqual(m['recall_at_1'], 0.)
        self.assertEqual(m['mrr_at_4'], 1 / 3)
        self.assertEqual(m['recall_at_4'], 1.)
        self.assertEqual(retrieval_metrics([], ['A'], rows)['recall_at_1'], 0.)
        self.assertIsNone(retrieval_metrics([], [], rows)['recall_at_1'])
        self.assertEqual(retrieval_metrics(['forbidden', 'a'], ['A'], rows)['mrr_at_4'], .5)


class BM25Tests(unittest.TestCase):
    def test_frequencies_and_length_change_bm25_scores(self):
        rows = [{'chunk_id': str(i), 'title': '', 'text': text} for i, text in enumerate([
            'rare rare rare policy', 'rare policy', 'other document', 'unrelated material', 'irrelevant words'])]
        ranked = rank_bm25('rare', rows)
        self.assertEqual([r['chunk_id'] for r in ranked], ['0', '1'])
        self.assertGreater(ranked[0]['score'], ranked[1]['score'])
        self.assertEqual(rank_bm25('absent', rows), [])
        self.assertEqual(rank_bm25('', rows), [])
        self.assertEqual(rank_bm25('rare', []), [])

    def test_chinese_tokenizer_and_tiny_corpus(self):
        self.assertGreater(tokens('退款 退款').count('退款'), 1)
        rows = [{'chunk_id': 'one', 'title': '退款审批', 'text': '退款审批上限为500元'}]
        self.assertEqual(rank_bm25('退款审批', rows)[0]['chunk_id'], 'one')


class RerankerTests(unittest.TestCase):
    def test_scores_validate_shape_finiteness_and_ties(self):
        rows = [{'chunk_id': 'b'}, {'chunk_id': 'a'}]
        self.assertEqual([r['chunk_id'] for r in apply_scores(rows, [.5, .5], 2)], ['a', 'b'])
        for scores in ([1.], [math.nan, .1], [True, .1], [math.inf, .1]):
            with self.assertRaises(AccessError):
                apply_scores(rows, scores, 2)

    def test_http_index_mapping_and_budget(self):
        rows = [{'chunk_id': str(i), 'title': 'policy', 'text': str(i)} for i in range(2)]
        budget = Mock()
        def handler(request):
            payload = json.loads(request.content)
            self.assertEqual(payload['top_n'], 2)
            return httpx.Response(200, json={'results': [
                {'index': 1, 'relevance_score': .9}, {'index': 0, 'relevance_score': .1}]})
        original = httpx.Client
        with patch('rag_app.reranking.httpx.Client', side_effect=lambda **kw: original(transport=httpx.MockTransport(handler), **kw)):
            ranked = HTTPReranker('https://invalid/v1', 'fake', 'test', budget).rerank('q', rows, 1)
        self.assertEqual(ranked[0]['chunk_id'], '1')
        budget.assert_called_once_with('rerank')

    def test_http_rejects_incomplete_duplicate_and_invalid_results(self):
        rows = [{'chunk_id': str(i), 'title': '', 'text': str(i)} for i in range(2)]
        original = httpx.Client
        for results in ([], [{'index': 0, 'relevance_score': .1}] * 2,
                        [{'index': 5, 'relevance_score': .1}] * 2,
                        [{'index': 0, 'relevance_score': 'private'}, {'index': 1, 'relevance_score': .1}]):
            with patch('rag_app.reranking.httpx.Client', side_effect=lambda **kw: original(
                transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'results': results})), **kw)):
                with self.assertRaises(AccessError):
                    HTTPReranker('https://invalid', 'fake', 'fake').rerank('q', rows, 1)

    def test_local_cross_encoder_pairs_and_sort(self):
        model = CrossEncoderReranker('local-fixture')
        scores = Mock()
        scores.tolist.return_value = [.1, .9]
        model._model = Mock()
        model._model.predict.return_value = scores
        rows = [{'chunk_id': str(i), 'title': 'title', 'text': str(i)} for i in range(2)]
        self.assertEqual(model.rerank('query', rows, 1)[0]['chunk_id'], '1')
        self.assertEqual(model._model.predict.call_args.args[0], [('query', 'title\n0'), ('query', 'title\n1')])

    def test_missing_config_is_explicit(self):
        with patch.dict(os.environ, {'RAG_RERANKER': 'off'}):
            self.assertIsNone(configured_reranker())
        with patch.dict(os.environ, {'RAG_RERANKER': 'http', 'RAG_RERANK_MODEL': 'fake'}):
            with self.assertRaises(ValueError): configured_reranker()


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'db')
        populate(self.store)
        self.alice = Actor('alice', 'demo', ('support',))
        self.bob = Actor('bob', 'demo', ('engineering',))

    def test_langchain_retriever_is_permission_scoped(self):
        retriever = AuthorizedRetriever(store=self.store, actor=self.alice, method='bm25', k=4)
        docs = retriever.invoke('退款审批')
        self.assertEqual(docs[0].metadata['document_id'], 'C001')
        for method in ('bm25', 'hybrid-local'):
            answer = Service(self.store).ask('发布窗口 密钥轮换 退款审批', self.alice, method)
            self.assertTrue(all(not c['document_id'].startswith(('E', 'O')) for c in answer['citations']))

    def test_reranker_receives_authorized_candidates_and_changes_ranking(self):
        observed = []
        class Reranker:
            model_id = 'deterministic-score-fixture'
            def rerank(inner, query, rows, top_k):
                observed.extend(rows)
                return apply_scores(rows, [1. if r['document_id'] == 'S002' else 0. for r in rows], top_k)
        result = Service(self.store, reranker=Reranker()).ask('差旅报销 入职材料 密钥轮换', self.alice, 'hybrid-local', 1, True)
        self.assertTrue(observed)
        self.assertTrue(all(not r['document_id'].startswith(('E', 'O')) for r in observed))
        self.assertEqual(self.store.citation(result['retrieved_chunk_ids'][0], self.alice)['document_id'], 'S002')
        self.assertGreater(len(result['retrieval_trace']['pre_rerank_chunk_ids']), 1)

    def test_revocation_during_rerank_fails_closed(self):
        store = self.store
        class Revoker:
            model_id = 'fixture'
            def rerank(inner, query, rows, top_k):
                store.deactivate('C001')
                return rows[:top_k]
        with self.assertRaises(AccessError):
            Service(self.store, reranker=Revoker()).ask('退款审批', self.alice, 'bm25', rerank=True)

    def test_reranker_cannot_add_unauthorized_candidate(self):
        forbidden = next(r for r in self.store.authorized_chunks(self.bob) if r['document_id'] == 'E001')
        class Bad:
            model_id = 'fixture'
            def rerank(inner, query, rows, top_k): return [forbidden]
        with self.assertRaises(AccessError):
            Service(self.store, reranker=Bad()).ask('退款审批', self.alice, 'bm25', rerank=True)

    def test_api_topk_reranking_and_capabilities(self):
        class Reverse:
            model_id = 'fixture'
            def rerank(inner, query, rows, top_k): return list(reversed(rows))[:top_k]
        with patch.dict(os.environ, {'RAG_CHECKPOINT_DB': str(self.root / 'cp')}):
            with TestClient(create_app(store=self.store, auth=Registry({'fake': self.alice}), reranker=Reverse())) as client:
                capabilities = client.get('/capabilities').json()
                self.assertEqual(capabilities['orchestrator'], 'langgraph')
                for route in ('/ask', '/agent'):
                    response = client.post(route, headers={'Authorization': 'Bearer fake'},
                        json={'query': '差旅报销 入职材料', 'method': 'hybrid-local', 'top_k': 1, 'rerank': True})
                    self.assertEqual(response.status_code, 200)
                    result = response.json() if route == '/ask' else response.json()['results'][0]
                    self.assertEqual(len(result['retrieved_chunk_ids']), 1)
                    self.assertEqual(result['reranker_model'], 'fixture')

    def test_no_silent_rerank_fallback(self):
        with self.assertRaises(AccessError) as error:
            Service(self.store).ask('退款审批', self.alice, 'bm25', rerank=True)
        self.assertEqual(error.exception.reason, 'reranker_not_configured')

    def test_graph_resume_rejects_changed_ranking_options(self):
        cp = Checkpointer(self.root / 'cp')
        execute(Service(self.store), cp, '退款审批', self.alice, method='bm25', workflow_id='same', top_k=1)
        with self.assertRaises(AccessError):
            execute(Service(self.store), cp, '退款审批', self.alice, method='bm25', workflow_id='same', top_k=2)

    def test_graph_budget_and_tool_schema_block_overrides(self):
        class Malicious:
            def next(inner, messages):
                return {'name': 'search_knowledge', 'arguments': {'query': '密钥', 'actor': 'bob'}}
        with self.assertRaises(AccessError):
            execute(Service(self.store), Checkpointer(self.root / 'cp'), 'q', self.alice, Malicious())
        tools = authorized_tools(Service(self.store), self.alice)
        self.assertNotIn('actor', tools['search_knowledge'].args)

    def test_graph_records_nested_metadata_spans(self):
        with trace_scope() as batch:
            result = execute(Service(self.store), Checkpointer(self.root / 'cp'), '退款审批', self.alice, method='bm25')
        self.assertEqual(result['orchestrator'], 'langgraph')
        names = {s['name'] for s in batch.spans}
        self.assertTrue({'workflow.langgraph', 'workflow.plan', 'retrieve.bm25', 'generate'} <= names)
        self.assertEqual(len({s['traceId'] for s in batch.spans}), 1)
        exported = json.dumps(batch.spans, ensure_ascii=False)
        self.assertNotIn('退款审批', exported)
        self.assertNotIn('退款审批上限', exported)
        ids = {s['spanId'] for s in batch.spans}
        self.assertTrue(all(s['parentSpanId'] in ids for s in batch.spans if 'parentSpanId' in s))

    def test_api_exports_one_connected_trace_without_question_or_document(self):
        tracer = LangfuseTracer('https://invalid', 'fake', 'fake-secret')
        accepted = httpx.Response(200, json={}, request=httpx.Request('POST', 'https://invalid'))
        with patch.dict(os.environ, {'RAG_CHECKPOINT_DB': str(self.root / 'cp')}), \
             patch('rag_app.tracing.configured_tracer', return_value=tracer), \
             patch('rag_app.tracing.httpx.post', return_value=accepted) as post:
            with TestClient(create_app(store=self.store, auth=Registry({'private-token': self.alice}))) as client:
                response = client.post('/agent', headers={'Authorization': 'Bearer private-token'},
                                       json={'query': '退款审批', 'method': 'bm25'})
                self.assertEqual(response.status_code, 200)
        spans = post.call_args.kwargs['json']['resourceSpans'][0]['scopeSpans'][0]['spans']
        root = next(s for s in spans if s['name'] == '/agent')
        self.assertEqual(len({s['traceId'] for s in spans}), 1)
        self.assertFalse('parentSpanId' in root)
        self.assertGreater(len(spans), 5)
        raw = json.dumps(spans, ensure_ascii=False)
        for private in ('退款审批', 'private-token', 'fake-secret', 'alice'):
            self.assertNotIn(private, raw)


class LangChainPlannerTests(unittest.TestCase):
    def test_native_messages_tools_and_usage(self):
        llm = Mock()
        llm.bind_tools.return_value.invoke.return_value = AIMessage(content='', tool_calls=[
            {'name': 'search_knowledge', 'args': {'query': 'q'}, 'id': 'id'}],
            usage_metadata={'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15})
        budget = Mock()
        planner = LangChainPlanner('https://invalid', 'fake', 'fixture', budget, llm)
        call = planner.next([{'role': 'user', 'content': 'q'}])
        self.assertEqual(call, {'name': 'search_knowledge', 'arguments': {'query': 'q'}})
        self.assertEqual(planner.usage_records[-1]['usage']['total_tokens'], 15)
        budget.assert_called_once_with('chat')

    def test_parallel_model_calls_rejected(self):
        llm = Mock()
        llm.bind_tools.return_value.invoke.return_value = AIMessage(content='', tool_calls=[
            {'name': 'search_knowledge', 'args': {'query': 'q'}, 'id': str(i)} for i in range(2)])
        with self.assertRaises(AccessError):
            LangChainPlanner('https://invalid', 'fake', 'fixture', llm=llm).next([])


class TraceBatchTests(unittest.TestCase):
    def test_parent_ids_failure_and_export_protocol(self):
        with trace_scope() as batch:
            with span('root'):
                with self.assertRaises(RuntimeError):
                    with span('child') as meta:
                        meta['query'] = 'do-not-export'
                        meta['input_tokens'] = 3
                        raise RuntimeError('do-not-export')
        child, root = batch.spans
        self.assertEqual(child['parentSpanId'], root['spanId'])
        self.assertEqual(child['status']['code'], 2)
        self.assertNotIn('do-not-export', json.dumps(batch.spans))
        tracer = LangfuseTracer('https://invalid', 'fake', 'fake-secret')
        response = httpx.Response(200, json={}, request=httpx.Request('POST', 'https://invalid'))
        with patch('rag_app.tracing.httpx.post', return_value=response) as post:
            tracer.export(batch)
        self.assertEqual(tracer.last_status, 'accepted')
        self.assertEqual(len(post.call_args.kwargs['json']['resourceSpans'][0]['scopeSpans'][0]['spans']), 2)
