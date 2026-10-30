"""Re-evaluate reviewed user feedback under the operator's current user credentials."""
import argparse
import json
import os
from pathlib import Path
import statistics
from rag_app.security import Registry,AccessError
from rag_app.metrics import retrieval_metrics


def evaluate_records(service,actor,records,methods):
    results=[]
    for method in methods:
        rows=[]
        for record in records:
            label=record['feedback']
            if not label.get('reviewed') or type(label.get('expected_refusal')) is not bool:
                continue
            authorized={c['chunk_id']:c for c in service.store.authorized_chunks(actor)}
            visible={c['document_id'] for c in authorized.values()}
            expected=set(label.get('expected_doc_ids',[]))
            if not expected<=visible:
                rows.append({'run_id':record['run_id'],'status':'skipped_revoked_label'})
                continue
            result=service.ask(record['query'],actor,method,4)
            rows.append({'run_id':record['run_id'],'status':'evaluated',
                         **retrieval_metrics(result['retrieved_chunk_ids'],expected,authorized),
                         'refusal_correct':result['refused']==label['expected_refusal'],
                         'evidence_status':result['evidence_check']['status']})
        valid=[r for r in rows if r['status']=='evaluated']
        mean=lambda key:statistics.mean([r[key] for r in valid if r[key] is not None]) if any(r[key] is not None for r in valid) else None
        results.append({'method':method,'evaluated':len(valid),'metrics':{k:mean(k) for k in ('recall_at_1','recall_at_4','hit_at_1','mrr_at_4','refusal_correct')},'rows':rows})
    return {'format':'rag-feedback-evaluation-v1','results':results,
            'limitations':['Only explicitly reviewed labels are evaluated.','Corrected answer text is not an automatic semantic-quality score.']}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--env-file')
    p.add_argument('--methods',nargs='+',choices=['bm25','hybrid-local','pgvector','hybrid'],default=['bm25','hybrid-local'])
    p.add_argument('--allow-external',action='store_true')
    a=p.parse_args()
    if a.env_file:
        from dotenv import load_dotenv
        load_dotenv(a.env_file,override=False)
    if not os.getenv('RAG_EVAL_TOKEN'):p.error('Set RAG_EVAL_TOKEN to a valid local user token')
    if (os.getenv('RAG_EVIDENCE_MODE')=='model' or os.getenv('RAG_EMBEDDING')=='real') and not a.allow_external:
        p.error('Configured model/embedding evaluation requires --allow-external')
    target=Path(a.out)
    if target.exists():p.error('Choose a fresh output report path')
    source=json.loads(Path(a.input).read_text(encoding='utf-8-sig'))
    if source.get('format')!='rag-feedback-v1':p.error('Expected a /feedback/export file')
    from rag_app.api import create_app
    from rag_app.generation import ExtractiveGenerator
    auth=Registry.from_file(os.getenv('RAG_AUTH_FILE','data/demo_auth.json'))
    actor=auth.authenticate('Bearer '+os.environ['RAG_EVAL_TOKEN'])
    app=create_app(auth=auth,generator=ExtractiveGenerator())
    # Do not trust actor/group fields in an imported dataset; use the current token.
    report=evaluate_records(app.state.service,actor,source['records'],a.methods)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Reviewed-feedback evaluation written; unreviewed and revoked labels were excluded.')


if __name__=='__main__':main()
