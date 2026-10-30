"""Explicit live-service probes. Missing configuration is skipped, never called a pass."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import httpx


def configured(*names):
    return all(os.getenv(n) and not any(s in os.getenv(n).lower() for s in ('replace_me','replace-with','your-','.invalid')) for n in names)


def probe(service,allow_external=False):
    if service=='app':
        if not configured('RAG_VERIFY_APP_URL','RAG_VERIFY_APP_TOKEN'):return 'not_configured',{}
        with httpx.Client(base_url=os.environ['RAG_VERIFY_APP_URL'],timeout=30) as client:
            health=client.get('/health');health.raise_for_status()
            answer=client.post('/ask',headers={'Authorization':'Bearer '+os.environ['RAG_VERIFY_APP_TOKEN']},
                json={'query':'差旅报销的规定是什么？','method':'bm25'})
            answer.raise_for_status();body=answer.json()
        if not all(k in body for k in ('run_id','refused','evidence_check','citations')):raise ValueError()
        return 'verified',{'check':'authenticated_ask_contract','refused':body['refused']}
    required={'postgres':['RAG_PG_DSN'],'embedding':['RAG_EMBED_URL','RAG_EMBED_KEY','RAG_EMBED_MODEL','RAG_EMBED_DIM'],
        'rerank':['RAG_RERANK_MODEL'],'model':['RAG_MODEL_URL','RAG_MODEL_KEY','RAG_MODEL_NAME'],
        'langfuse':['LANGFUSE_BASE_URL','LANGFUSE_PUBLIC_KEY','LANGFUSE_SECRET_KEY'],
        'dify':['DIFY_API_BASE_URL','DIFY_API_KEY'],'coze':['COZE_API_BASE_URL','COZE_API_TOKEN','COZE_WORKFLOW_ID']}
    if not configured(*required[service]):return 'not_configured',{}
    if service!='postgres' and not allow_external:return 'external_opt_in_required',{}
    if service=='postgres':
        import psycopg
        with psycopg.connect(os.environ['RAG_PG_DSN'],connect_timeout=5) as c:
            version=c.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
            if version is None:raise ValueError()
        return 'verified',{'check':'postgres_connection_and_pgvector_extension','pgvector_version':version[0]}
    from rag_app.request_budget import PersistentBudget
    budget=PersistentBudget(os.environ.get('RAG_BUDGET_DB','data/service_probe_budget.sqlite3'))
    if service=='embedding':
        from rag_app.embedding import HTTPEmbedding
        adapter=HTTPEmbedding(os.environ['RAG_EMBED_URL'],os.environ['RAG_EMBED_KEY'],os.environ['RAG_EMBED_MODEL'],int(os.environ['RAG_EMBED_DIM']),budget)
        vectors=adapter.embed(['Synthetic policy: expenses must be submitted within 15 days.'])
        return 'verified',{'check':'embedding_response_shape','dimensions':len(vectors[0])}
    if service=='rerank':
        from rag_app.reranking import configured_reranker
        adapter=configured_reranker(budget)
        if adapter is None:return 'not_configured',{}
        rows=[{'chunk_id':'one','title':'Expenses','text':'Submit expenses within 15 days.'},
              {'chunk_id':'two','title':'Weather','text':'A synthetic weather sentence.'}]
        result=adapter.rerank('When should expenses be submitted?',rows,2)
        return 'verified',{'check':'reranker_response_shape','returned':len(result)}
    if service=='model':
        from rag_app.generation import HTTPQuoteGenerator
        adapter=HTTPQuoteGenerator(os.environ['RAG_MODEL_URL'],os.environ['RAG_MODEL_KEY'],os.environ['RAG_MODEL_NAME'],budget)
        result=adapter.generate('What is the expense deadline?',[{'chunk_id':'synthetic','text':'Expenses must be submitted within 15 days.'}])
        claims=result['claims']
        if (not isinstance(claims,list) or any(c.get('chunk_id')!='synthetic' or not c.get('quote') or
                c['quote'] not in 'Expenses must be submitted within 15 days.' for c in claims)):raise ValueError()
        return 'verified',{'check':'model_quote_contract','supported_claims':len(claims)}
    if service=='langfuse':
        from rag_app.tracing import LangfuseTracer
        tracer=LangfuseTracer(os.environ['LANGFUSE_BASE_URL'],os.environ['LANGFUSE_PUBLIC_KEY'],os.environ['LANGFUSE_SECRET_KEY'])
        tracer.record('/integration-check',1,200)
        if tracer.last_status!='accepted':raise ValueError()
        return 'verified',{'check':'otlp_ingestion_accepted','note':'Dashboard visibility was not independently checked.'}
    if service=='dify':
        inputs=json.loads(os.getenv('DIFY_VERIFY_INPUTS','{"query":"差旅报销的规定是什么？"}'))
        response=httpx.post(os.environ['DIFY_API_BASE_URL'].rstrip('/')+'/workflows/run',
            headers={'Authorization':'Bearer '+os.environ['DIFY_API_KEY']},
            json={'inputs':inputs,'response_mode':'blocking','user':'rag-integration-probe'},timeout=45)
        response.raise_for_status();body=response.json()
        if body.get('data',{}).get('status')!='succeeded':raise ValueError()
        return 'verified',{'check':'published_dify_workflow_succeeded',
            'note':'Configure the example workflow to call this RAG backend for an end-to-end platform check.'}
    if service=='coze':
        parameters=json.loads(os.getenv('COZE_VERIFY_PARAMETERS','{"query":"差旅报销的规定是什么？"}'))
        response=httpx.post(os.environ['COZE_API_BASE_URL'].rstrip('/')+'/v1/workflow/run',
            headers={'Authorization':'Bearer '+os.environ['COZE_API_TOKEN']},json={
                'workflow_id':os.environ['COZE_WORKFLOW_ID'],'parameters':parameters,'is_async':False},timeout=45)
        response.raise_for_status();body=response.json()
        if body.get('code')!=0 or 'data' not in body:raise ValueError()
        return 'verified',{'check':'published_coze_workflow_succeeded',
            'note':'Configure the example workflow to call this RAG backend for an end-to-end platform check.'}


def run_probes(services,allow_external=False):
    rows=[]
    for service in services:
        try:
            status,details=probe(service,allow_external)
        except Exception:
            status,details='failed',{'reason':'probe_failed','note':'Upstream error bodies, URLs and credentials are withheld.'}
        rows.append({'service':service,'status':status,'details':details})
    return {'generated_at':datetime.now(timezone.utc).isoformat(),'results':rows,
            'summary':{s:sum(r['status']==s for r in rows) for s in ('verified','failed','not_configured','external_opt_in_required')},
            'scope':'Live protocols and service availability; this is not a model-quality or production-load benchmark.'}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--env-file')
    p.add_argument('--services',nargs='+',choices=['app','postgres','embedding','rerank','model','langfuse','dify','coze'],
                   default=['postgres','embedding','rerank','model','langfuse','dify','coze'])
    p.add_argument('--allow-external',action='store_true')
    p.add_argument('--strict',action='store_true',help='Exit nonzero if any requested check did not verify')
    p.add_argument('--out',required=True)
    a=p.parse_args()
    if a.env_file:
        from dotenv import load_dotenv
        if not Path(a.env_file).is_file():p.error('Environment file not found')
        load_dotenv(a.env_file,override=False)
    target=Path(a.out)
    if target.exists():p.error('Choose a fresh report path')
    report=run_probes(a.services,a.allow_external)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report['summary']))
    if report['summary']['failed'] or (a.strict and report['summary']['verified']!=len(a.services)):
        raise SystemExit(1)


if __name__=='__main__':main()
