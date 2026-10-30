"""Fixed-set paired evaluation. Default dev only. Test split requires explicit opt-in."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics
import tempfile
from init_demo import populate
from rag_app.security import Actor
from rag_app.service import Service
from rag_app.store import Store
from rag_app.metrics import retrieval_metrics
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parent
ACTORS={"alice":Actor("alice","demo",("support",)),"bob":Actor("bob","demo",("engineering",))}
def average(values):return statistics.mean(values) if values else None
def percentile(values,p):
    return sorted(values)[max(0,math.ceil(len(values)*p)-1)] if values else None

def evaluate(store,questions,method,service=None,rerank=False):
    service=service or Service(store)
    rows=[]
    for q in questions:
        actor=ACTORS[q["actor"]];result=service.ask(q["query"],actor,method,4,rerank=rerank)
        authorized={c["chunk_id"]:c for c in store.authorized_chunks(actor)}
        retrieved={authorized[c]["document_id"] for c in result["retrieved_chunk_ids"] if c in authorized}
        expected=set(q["expected_doc_ids"])
        ranking=retrieval_metrics(result['retrieved_chunk_ids'],expected,authorized)
        before=retrieval_metrics((result.get('retrieval_trace') or {}).get('pre_rerank_chunk_ids',result['retrieved_chunk_ids']),expected,authorized)
        citations=result["citations"]
        exact_support=sum(c["chunk_id"] in authorized and c["quote"] in authorized[c["chunk_id"]]["text"] for c in citations)
        rows.append({"question_id":q["question_id"],"category":q["category"],
            **ranking,"before_rerank":before,
            "ordered_retrieved_chunk_ids":result['retrieved_chunk_ids'],
            "ordered_retrieved_doc_ids":[authorized[c]['document_id'] if c in authorized else None for c in result['retrieved_chunk_ids']],
            "retrieved_docs":sorted(retrieved),"expected_docs":sorted(expected),
            "expected_refusal":q["expected_refusal"],"actual_refusal":result["refused"],
            "refusal_correct":result["refused"]==q["expected_refusal"],
            "reference_points_covered":sum(p in result["answer"] for p in q["reference_points"]),
            "reference_points_total":len(q["reference_points"]),
            "citations_total":len(citations),"citations_exact_support":exact_support,
            "retrieval_leaks":sum(c not in authorized for c in result["retrieved_chunk_ids"]),
            "context_leaks":sum(c not in authorized for c in result["context_chunk_ids"]),
            "output_leaks":sum(c["chunk_id"] not in authorized for c in citations),
            "latency_ms":result["latency_ms"],"answer":result["answer"],"citations":citations,"evidence_check":result.get("evidence_check"),"refusal_reason":result.get("refusal_reason")})
    total_citations=sum(r["citations_total"] for r in rows)
    positive=[r for r in rows if not r["expected_refusal"]]
    negative=[r for r in rows if r["expected_refusal"]]
    metrics={"n":len(rows),"recall_at_4_macro":average([r["recall_at_4"] for r in rows if r["recall_at_4"] is not None]),
        **{name+'_macro':average([r[name] for r in rows if r[name] is not None]) for name in ('recall_at_1','hit_at_1','mrr_at_4')},
        'before_rerank_recall_at_1_macro':average([r['before_rerank']['recall_at_1'] for r in rows if r['before_rerank']['recall_at_1'] is not None]),
        "quote_support_rate":sum(r["citations_exact_support"] for r in rows)/total_citations if total_citations else None,
        "quote_support_note":"Exact substring support only; does not measure semantic relevance or completeness.",
        "correct_refusal_rate":average([r["actual_refusal"] for r in negative]),
        "false_refusal_rate":average([r["actual_refusal"] for r in positive]),
        "missing_citations_on_answerable":sum(r["citations_total"]==0 for r in positive),
        "reference_point_coverage":sum(r["reference_points_covered"] for r in positive)/sum(r["reference_points_total"] for r in positive),
        "leak_events":{key:sum(r[key] for r in rows) for key in ("retrieval_leaks","context_leaks","output_leaks")},
        "latency_p50_ms":percentile([r["latency_ms"] for r in rows],.5),
        "latency_p95_ms":percentile([r["latency_ms"] for r in rows],.95),
        "cache":"no answer cache; sequential local SQLite reads; not a load test",
        "model":service.generator.model_id,"embedding":getattr(service.pg_index,'model_id',None) if method in ('pgvector','hybrid') else 'lexical-hash-sha256-256-v1' if method in ('hash-vector','hybrid-local') else None,
        'reranker':service.reranker.model_id if rerank else None,
        "token_usage":None,"cost":None if method in ('pgvector','hybrid') or rerank else 0.0,"cost_note":"External cost not calculated; offline baselines make no external API calls.",
        "index_version":store.index_version}
    return {"method":method,"rerank":rerank,"metrics":metrics,"rows":rows}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--split",choices=["dev","test"],default="dev")
    p.add_argument("--allow-test",action="store_true")
    p.add_argument("--out",default=None)
    p.add_argument('--env-file',help='Explicitly load a local environment file')
    p.add_argument('--methods',nargs='+',choices=['keyword','hash-vector','bm25','hybrid-local','pgvector','hybrid'],default=['keyword','hash-vector','bm25','hybrid-local'])
    p.add_argument('--runtime',action='store_true',help='Use the configured store/index instead of a temporary offline store')
    p.add_argument('--compare-rerank',action='store_true',help='Compare every method before and after the configured reranker')
    p.add_argument('--allow-external',action='store_true',help='Allow configured embedding or HTTP reranking requests')
    a=p.parse_args()
    if a.split=="test" and not a.allow_test:p.error("Final split requires --allow-test; freeze choices before use")
    import os
    if a.env_file:
        from dotenv import load_dotenv
        if not os.path.isfile(a.env_file):p.error('Environment file not found')
        load_dotenv(a.env_file,override=False)
    needs_pg=any(m in ('pgvector','hybrid') for m in a.methods)
    if needs_pg and not a.runtime:p.error('pgvector/hybrid require --runtime and an explicitly built PostgreSQL index')
    if a.compare_rerank and os.getenv('RAG_RERANKER','off')=='off':p.error('Configure RAG_RERANKER before --compare-rerank')
    external=(needs_pg and os.getenv('RAG_EMBEDDING')=='real') or (a.compare_rerank and os.getenv('RAG_RERANKER')=='http') or os.getenv('RAG_EVIDENCE_MODE')=='model'
    if external and not a.allow_external:p.error('External evaluation requires --allow-external')
    path=ROOT/"data/questions.json";raw=path.read_bytes();data=json.loads(raw)
    questions=[q for q in data["questions"] if q["split"]==a.split]
    out=Path(a.out) if a.out else ROOT/"reports"/(a.split+".json")
    if out.exists():p.error("Report exists; preserve evidence and choose a new --out path")
    with tempfile.TemporaryDirectory() as td:
        if a.runtime:
            from rag_app.settings import open_store
            from rag_app.api import create_app
            from rag_app.security import Registry
            store=open_store()
            # Evaluate retrieval with extractive answers, regardless of chat configuration.
            from rag_app.generation import ExtractiveGenerator
            service=create_app(store=store,auth=Registry({}),generator=ExtractiveGenerator()).state.service
            if needs_pg and service.pg_index is None:p.error('RAG_PG_DSN is required')
        else:
            from rag_app.reranking import configured_reranker
            from rag_app.request_budget import PersistentBudget
            store=Store(Path(td)/'eval.sqlite3');populate(store)
            budget=PersistentBudget(os.environ['RAG_BUDGET_DB']) if a.allow_external and os.getenv('RAG_BUDGET_DB') else None
            from rag_app.evidence_policy import configured_evidence_policy
            service=Service(store,reranker=configured_reranker(budget) if a.compare_rerank else None,evidence_policy=configured_evidence_policy(budget))
        results=[evaluate(store,questions,m,service,rerank) for m in a.methods for rerank in ([False,True] if a.compare_rerank else [False])]
    report={"dataset_version":data["version"],"dataset_sha256":hashlib.sha256(raw).hexdigest(),
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'pipeline':{'chunker':'markdown-sections-v1','corrective':service.corrective,'section_context':service.expand_context},
        'mode':'configured-runtime' if a.runtime else 'offline-synthetic',
        'metric_unit':'document relevance on first k ranked chunks; duplicate documents count once in recall; MRR uses chunk positions',
        "split":a.split,"seed":data["seed"],"category_counts":dict(Counter(q["category"] for q in questions)),
        "limitations":[data["note"],"Synthetic small sample; no human semantic scoring. Only explicitly selected methods were evaluated.",
                       "Hash-vector baseline is lexical, not a pretrained semantic embedding model."],"results":results}
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=[f"# {a.split} 固定集评测","",f"数据集 SHA-256：{report['dataset_sha256']}","",
           '|方法|重排|题数|Recall@1|Hit@1|Recall@4|MRR@4|正确拒答|正常题误拒答|', '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in results:
        m=r["metrics"]
        fmt=lambda v:'N/A' if v is None else f'{v:.3f}'
        lines.append('|'+ '|'.join([r['method'],'yes' if r['rerank'] else 'no',str(m['n']),*[fmt(m[key]) for key in ('recall_at_1_macro','hit_at_1_macro','recall_at_4_macro','mrr_at_4_macro','correct_refusal_rate','false_refusal_rate')]])+'|')
    lines+=['', 'Recall@1 按相关文档总数归一化；多文档题命中第一篇不等于召回全部。Hit@1 单独统计首位是否相关。无相关文档的拒答题不参与召回平均。', '', '排序位置按返回片段计算，相关性按文档标注；同一文档在 Recall 分子只计一次。', '', 'hybrid-local 使用 BM25 + 词项哈希向量，不代表真实语义 Embedding 效果。', '', '只有显式配置并选中的方法才被测试；小样本结果不能外推生产效果。完整明细见同名 JSON。']
    for r in results:
        failures=[v["question_id"] for v in r["rows"] if not v["refusal_correct"] or v["recall_at_4"] not in (None,1.0) or v["reference_points_covered"]<v["reference_points_total"]]
        lines.append(f"- {r['method']} 待分析题目："+("、".join(failures) or "本固定集无上述类型失败；仍不能外推零风险。"))
    out.with_suffix(".md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({r['method']+('+rerank' if r['rerank'] else ''):r['metrics'] for r in results},ensure_ascii=False,indent=2))
if __name__=="__main__":main()

