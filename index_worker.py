"""Run queued index jobs after a restart; external embeddings require opt-in."""
import argparse
import json
import os
from rag_app.security import Actor,Registry


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--env-file')
    p.add_argument('--allow-external',action='store_true')
    a=p.parse_args()
    if a.env_file:
        from dotenv import load_dotenv
        load_dotenv(a.env_file,override=False)
    if os.getenv('RAG_EMBEDDING')=='real' and not a.allow_external:
        p.error('Real embedding jobs require --allow-external')
    from rag_app.api import create_app
    from rag_app.settings import open_store
    store=open_store();app=create_app(store=store,auth=Registry({}));state=app.state.application_state
    with store.connect() as c:
        rows=state.sql(c,"SELECT * FROM app_jobs WHERE status='queued' ORDER BY created").fetchall()
    for row in rows:
        actor=Actor(row['actor'],row['tenant'],())
        app.state.documents.run_index_job(actor,row['id'])
    print(json.dumps({'processed':len(rows),'note':'Already running or failed jobs are not replayed automatically.'}))


if __name__=='__main__':main()
