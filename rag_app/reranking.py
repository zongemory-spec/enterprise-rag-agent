"""Opt-in local CrossEncoder or compatible HTTP reranking, never an LLM sort."""
import math
import os
import threading
import httpx
from rag_app.security import AccessError


def apply_scores(rows, scores, top_k):
    if len(scores) != len(rows) or any(type(s) not in (float, int) or not math.isfinite(s) for s in scores):
        raise AccessError('invalid_reranker_scores', 502)
    ranked = [dict(row, rerank_score=float(score)) for row, score in zip(rows, scores)]
    ranked.sort(key=lambda row: (-row['rerank_score'], row['chunk_id']))
    return ranked[:top_k]


class CrossEncoderReranker:
    def __init__(self, model, device='cpu', revision=None):
        self.model_id = model
        self.device, self.revision = device, revision
        self._model = None
        self._lock = threading.Lock()

    def rerank(self, query, rows, top_k):
        if not rows:
            return []
        with self._lock:
            if self._model is None:
                try:
                    from sentence_transformers import CrossEncoder
                    self._model = CrossEncoder(self.model_id, device=self.device,
                                               revision=self.revision, trust_remote_code=False)
                except (ImportError, OSError, ValueError):
                    raise AccessError('reranker_model_unavailable', 503) from None
            scores = self._model.predict([(query, r['title'] + '\n' + r['text']) for r in rows],
                                         show_progress_bar=False).tolist()
        return apply_scores(rows, scores, top_k)


class HTTPReranker:
    """POST /rerank: {model, query, documents, top_n}; indexed results required."""
    def __init__(self, base_url, key, model, before_request=None):
        self.base_url, self.key, self.model_id = base_url.rstrip('/'), key, model
        self.before_request = before_request

    def rerank(self, query, rows, top_k):
        if not rows:
            return []
        if self.before_request:
            self.before_request('rerank')
        try:
            with httpx.Client(timeout=20) as client:
                response = client.post(self.base_url + '/rerank', headers={'Authorization': 'Bearer ' + self.key},
                    json={'model': self.model_id, 'query': query,
                          'documents': [r['title'] + '\n' + r['text'] for r in rows], 'top_n': len(rows)})
            response.raise_for_status()
            results = response.json()['results']
            if not isinstance(results, list) or len(results) != len(rows):
                raise ValueError()
            scores = [None] * len(rows)
            for item in results:
                idx = item['index']
                if type(idx) is not int or not 0 <= idx < len(rows) or scores[idx] is not None:
                    raise ValueError()
                scores[idx] = item['relevance_score']
            return apply_scores(rows, scores, top_k)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise AccessError('reranker_request_failed', 502) from None


def configured_reranker(budget=None):
    mode = os.getenv('RAG_RERANKER', 'off')
    if mode == 'off':
        return None
    model = os.getenv('RAG_RERANK_MODEL')
    if not model:
        raise ValueError('RAG_RERANK_MODEL is required')
    if mode == 'cross-encoder':
        return CrossEncoderReranker(model, os.getenv('RAG_RERANK_DEVICE', 'cpu'),
                                   os.getenv('RAG_RERANK_REVISION'))
    if mode == 'http':
        if budget is None:
            raise ValueError('HTTP reranking requires RAG_BUDGET_DB')
        return HTTPReranker(os.environ['RAG_RERANK_URL'], os.environ['RAG_RERANK_KEY'], model, budget)
    raise ValueError('RAG_RERANKER must be off, cross-encoder or http')
