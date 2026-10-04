"""Two bounded real embedding queries, zero chat; retain three retrieval rankings."""
import json
import os
from pathlib import Path
from rag_app.settings import configure_runtime,open_store
from rag_app.request_budget import PersistentBudget
from rag_app.embedding import HTTPEmbedding
from rag_app.pg_native_index import NativePGIndex
from rag_app.retrieval import rank
from rag_app.hybrid import fuse
from rag_app.security import Actor
from rag_app.service import Service

if __name__=='__main__':
    configure_runtime(semantic=True);store=open_store();shared=PersistentBudget(os.environ['RAG_BUDGET_DB'])
    cap={'used':0}
    def guard(kind):
        if cap['used']>=2:raise RuntimeError('This smoke permits at most two embedding attempts.')
        cap['used']+=1;shared(kind)
    embedding=HTTPEmbedding(os.environ['RAG_EMBED_URL'],os.environ['RAG_EMBED_KEY'],os.environ['RAG_EMBED_MODEL'],int(os.environ['RAG_EMBED_DIM']),guard)
    index=NativePGIndex(store,embedding);assert index.status()['ready']
    actor=Actor('alice','demo',('support',));reports=[]
    for query in ['退款审批条件是什么？','买错了能退钱吗？']:
        result=Service(store,pg_index=index).ask(query,actor,'hybrid',4)
        trace=result['retrieval_trace']
        assert trace['vector_candidates'] and len(set(result['context_chunk_ids']))==len(result['context_chunk_ids'])
        for cid in trace['keyword_candidates']+trace['vector_candidates']:
            source=store.citation(cid,actor);assert source['tenant_id']=='demo' and not source['document_id'].startswith(('E','O'))
        reports.append({'query':query,'answer':result['answer'],'retrieval_trace':trace,'citations':result['citations']})
    assert reports[0]['retrieval_trace']['keyword_candidates']
    report={'queries':reports,'model':index.model_id,'embedding_attempts':cap['used'],'chat_attempts':0,'budget':shared.status(),'scope':'Two synthetic smoke queries prove routing/fusion, not general quality improvement.'}
    Path('reports/hybrid-v3.4.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'embedding_attempts':cap['used'],'chat_attempts':0,'budget':shared.status(),'both_channels_first_query':bool(reports[0]['retrieval_trace']['keyword_candidates'] and reports[0]['retrieval_trace']['vector_candidates'])}))
