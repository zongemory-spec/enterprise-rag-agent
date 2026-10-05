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

ROOT=Path(__file__).resolve().parent
ACTORS={"alice":Actor("alice","demo",("support",)),"bob":Actor("bob","demo",("engineering",))}
def average(values):return statistics.mean(values) if values else None
def percentile(values,p):
    return sorted(values)[max(0,math.ceil(len(values)*p)-1)] if values else None

def evaluate(store,questions,method):
    service=Service(store)
    rows=[]
    for q in questions:
        actor=ACTORS[q["actor"]];result=service.ask(q["query"],actor,method,4)
        authorized={c["chunk_id"]:c for c in store.authorized_chunks(actor)}
        retrieved={authorized[c]["document_id"] for c in result["retrieved_chunk_ids"] if c in authorized}
        expected=set(q["expected_doc_ids"])
        citations=result["citations"]
        exact_support=sum(c["chunk_id"] in authorized and c["quote"] in authorized[c["chunk_id"]]["text"] for c in citations)
        rows.append({"question_id":q["question_id"],"category":q["category"],
            "recall_at_4":len(expected & retrieved)/len(expected) if expected else None,
            "retrieved_docs":sorted(retrieved),"expected_docs":sorted(expected),
            "expected_refusal":q["expected_refusal"],"actual_refusal":result["refused"],
            "refusal_correct":result["refused"]==q["expected_refusal"],
            "reference_points_covered":sum(p in result["answer"] for p in q["reference_points"]),
            "reference_points_total":len(q["reference_points"]),
            "citations_total":len(citations),"citations_exact_support":exact_support,
            "retrieval_leaks":sum(c not in authorized for c in result["retrieved_chunk_ids"]),
            "context_leaks":sum(c not in authorized for c in result["context_chunk_ids"]),
            "output_leaks":sum(c["chunk_id"] not in authorized for c in citations),
            "latency_ms":result["latency_ms"],"answer":result["answer"],"citations":citations})
    total_citations=sum(r["citations_total"] for r in rows)
    positive=[r for r in rows if not r["expected_refusal"]]
    negative=[r for r in rows if r["expected_refusal"]]
    metrics={"n":len(rows),"recall_at_4_macro":average([r["recall_at_4"] for r in rows if r["recall_at_4"] is not None]),
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
        "model":"extractive-facts-v1","embedding":"lexical-hash-sha256-256-v1" if method=="hash-vector" else None,
        "token_usage":None,"cost":0.0,"cost_note":"Offline local computation; no external API calls, not a measured inference price.",
        "index_version":store.index_version}
    return {"method":method,"metrics":metrics,"rows":rows}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--split",choices=["dev","test"],default="dev")
    p.add_argument("--allow-test",action="store_true")
    p.add_argument("--out",default=None)
    a=p.parse_args()
    if a.split=="test" and not a.allow_test:p.error("Final split requires --allow-test; freeze choices before use")
    path=ROOT/"data/questions.json";raw=path.read_bytes();data=json.loads(raw)
    questions=[q for q in data["questions"] if q["split"]==a.split]
    out=Path(a.out) if a.out else ROOT/"reports"/(a.split+".json")
    if out.exists():p.error("Report exists; preserve evidence and choose a new --out path")
    with tempfile.TemporaryDirectory() as td:
        store=Store(Path(td)/"eval.sqlite3");populate(store)
        results=[evaluate(store,questions,m) for m in ("keyword","hash-vector")]
    report={"dataset_version":data["version"],"dataset_sha256":hashlib.sha256(raw).hexdigest(),
        "split":a.split,"seed":data["seed"],"category_counts":dict(Counter(q["category"] for q in questions)),
        "limitations":[data["note"],"Synthetic small sample; no human semantic scoring; no real model or pgvector evaluation.",
                       "Hash-vector baseline is lexical, not a pretrained semantic embedding model."],"results":results}
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=[f"# {a.split} 固定集评测","",f"数据集 SHA-256：{report['dataset_sha256']}","",
           "|方法|题数|Recall@4|正确拒答|正常题误拒答|参考要点覆盖|","|---|---:|---:|---:|---:|---:|"]
    for r in results:
        m=r["metrics"]
        lines.append(f"|{r['method']}|{m['n']}|{m['recall_at_4_macro']:.3f}|{m['correct_refusal_rate']:.3f}|{m['false_refusal_rate']:.3f}|{m['reference_point_coverage']:.3f}|")
    lines+=["","这是离线抽取式回答与词项哈希对照，不是语义模型效果。全部明细和失败样例见同名 JSON。","小样本 p95 不代表线上稳定性；引用支持指标只检查逐字摘录，人工相关性评分尚未完成。"]
    for r in results:
        failures=[v["question_id"] for v in r["rows"] if not v["refusal_correct"] or v["recall_at_4"] not in (None,1.0) or v["reference_points_covered"]<v["reference_points_total"]]
        lines.append(f"- {r['method']} 待分析题目："+("、".join(failures) or "本固定集无上述类型失败；仍不能外推零风险。"))
    out.with_suffix(".md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({r["method"]:r["metrics"] for r in results},ensure_ascii=False,indent=2))
if __name__=="__main__":main()

