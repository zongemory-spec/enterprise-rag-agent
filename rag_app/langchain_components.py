"""LangChain retrieval and tool adapters bound to server-selected identity."""
from typing import Any
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field
from rag_app.bm25 import rank_bm25
from rag_app.retrieval import rank
from rag_app.hybrid import fuse
from rag_app.security import AccessError
from rag_app.tracing import span
from rag_app.sections import search_rows


class AuthorizedRetriever(BaseRetriever):
    store: Any = Field(exclude=True)
    actor: Any = Field(exclude=True)
    vector_index: Any = Field(default=None, exclude=True)
    method: str = 'bm25'
    k: int = 4
    trace: dict = Field(default_factory=dict, exclude=True)

    def _get_relevant_documents(self, query, *, run_manager):
        method = self.method
        if method not in ('keyword', 'hash-vector', 'bm25', 'pgvector', 'hybrid', 'hybrid-local'):
            raise ValueError('Unsupported retrieval method')
        self.trace.clear()
        if method in ('hybrid', 'hybrid-local'):
            window = max(12, self.k * 3)
            with span('retrieve.bm25'):
                lexical = rank_bm25(query, search_rows(self.store.authorized_chunks(self.actor)), window)
            with span('retrieve.vector'):
                vector = self._vector(query, window, local=method == 'hybrid-local')
            # Both inputs must be authorized before fusion or exposure to a reranker.
            for row in lexical + vector:
                self.store.citation(row['chunk_id'], self.actor)
            with span('retrieve.rrf'):
                rows = fuse(lexical, vector, self.k)
            self.trace.update(fusion='rrf', lexical='bm25', rank_constant=60, candidate_window=window,
                vector_kind='lexical-hash' if method == 'hybrid-local' else getattr(self.vector_index, 'model_id', 'unknown'),
                keyword_candidates=[r['chunk_id'] for r in lexical],
                vector_candidates=[r['chunk_id'] for r in vector])
        elif method == 'pgvector':
            with span('retrieve.vector'):
                rows = self._vector(query, self.k)
        else:
            with span('retrieve.' + method):
                authorized = search_rows(self.store.authorized_chunks(self.actor))
                rows = rank_bm25(query, authorized, self.k) if method == 'bm25' else rank(query, authorized, method, self.k)
        documents = []
        for row in rows:
            fresh = self.store.citation(row['chunk_id'], self.actor)
            metadata = {**fresh, **{key: row[key] for key in ('score', 'rrf_score', 'channel_ranks') if key in row}}
            documents.append(Document(page_content=fresh['text'], metadata=metadata))
        return documents

    def _vector(self, query, k, local=False):
        if local:
            return rank(query, search_rows(self.store.authorized_chunks(self.actor)), 'hash-vector', k)
        if self.vector_index is None:
            raise AccessError('pgvector_not_configured', 503)
        return self.vector_index.retrieve(self.store, self.actor, query, k)


class SearchArguments(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    query: str = Field(min_length=1, max_length=2000)


class TicketArguments(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    ticket_id: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')


def authorized_tools(service, actor, method='bm25', top_k=4, rerank=False):
    # Identity is captured by the server, never accepted as a model argument.
    def search_knowledge(query: str):
        return service.ask(query, actor, method, top_k, rerank=rerank)

    def get_ticket_status(ticket_id: str):
        return service.store.ticket(ticket_id, actor)

    return {
        'search_knowledge': StructuredTool.from_function(search_knowledge,
            description='Search knowledge accessible to the authenticated user.', args_schema=SearchArguments),
        'get_ticket_status': StructuredTool.from_function(get_ticket_status,
            description='Read the authenticated user ticket status.', args_schema=TicketArguments),
    }
