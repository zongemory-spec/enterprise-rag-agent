"""Explicit real API validation against synthetic documents; persistent attempt limits."""
import json
import os
from pathlib import Path
from rag_app.settings import configure_runtime,open_store
from rag_app.embedding import HTTPEmbedding
from rag_app.pg_native_index import NativePGIndex
from rag_app.request_budget import PersistentBudget
from rag_app.security import Actor,AccessError
from rag_app.retrieval import rank
from rag_app.planner import HTTPPlanner
from rag_app.synthesis import HTTPAnswerSynthesizer
from rag_app.service import Service
from rag_app.checkpoint import Checkpointer
from rag_app.workflow import execute
from init_demo import populate

if __name__=='__main__':
    configure_runtime(real=True,semantic=True);store=open_store();populate(store)
    budget=PersistentBudget(os.environ['RAG_BUDGET_DB'])
    embedding=HTTPEmbedding(os.environ['RAG_EMBED_URL'],os.environ['RAG_EMBED_KEY'],os.environ['RAG_EMBED_MODEL'],int(os.environ['RAG_EMBED_DIM']),budget)
    index=NativePGIndex(store,embedding)
    if not index.status()['ready']:index.sync()
    alice=Actor('alice','demo',('support',));bob=Actor('bob','demo',('engineering',))
    cases=[('买错了能退钱吗？','C001',alice),('出差花的钱怎样拿回来？','S001',alice),('新人报到要带些什么？','S002',alice),('上线之前哪些事项要确认？','E001',bob)]
    results=[]
    for query,expected,actor in cases:
        keyword=rank(query,store.authorized_chunks(actor),'keyword',4)
        semantic=index.retrieve(store,actor,query,4)
        ids=[r['document_id'] for r in semantic]
        assert all(r['tenant_id']==actor.tenant_id for r in semantic)
        if actor==alice:assert not any(i.startswith(('E','O')) for i in ids)
        results.append({'query':query,'expected_document':expected,'keyword_documents':[r['document_id'] for r in keyword],'semantic_documents':ids,'keyword_hit':any(r['document_id']==expected for r in keyword),'semantic_hit':expected in ids})
    args=[os.environ['RAG_MODEL_URL'],os.environ['RAG_MODEL_KEY'],os.environ['RAG_MODEL_NAME'],budget]
    answer=execute(Service(store,pg_index=index),Checkpointer(pg_store=store),'查询我的工单T1001当前状态，并查询退款审批条件，分别说明结果。不要猜测工单内容。',alice,HTTPPlanner(*args),'pgvector','semantic_smoke',HTTPAnswerSynthesizer(*args))
    assert answer['citations'] and '500' in answer['answer']
    assert {'search_knowledge','get_ticket_status'}<={r['tool'] for r in answer['trace']}
    denied=False
    try:store.ticket('T1001',bob)
    except AccessError:denied=True
    assert denied
    report={'index':index.status(),'budget':budget.status(),'cases':results,'keyword_hit_at_4':sum(r['keyword_hit'] for r in results)/len(results),'semantic_hit_at_4':sum(r['semantic_hit'] for r in results)/len(results),'agent_answer':answer['answer'],'agent_tools':answer['trace'],'bob_ticket_denied':denied,'embedding_usage':embedding.usage_records,'scope':'Four hand-written synthetic queries, not an independent benchmark; no general accuracy claim.'}
    Path('reports/semantic-v3.3.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('budget','keyword_hit_at_4','semantic_hit_at_4','agent_tools','bob_ticket_denied')},ensure_ascii=False))
