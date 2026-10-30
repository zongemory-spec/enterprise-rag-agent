"""Preview first by default; --apply deletes only the authenticated user's records."""
import argparse
import json
import os
from pathlib import Path


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--env-file')
    p.add_argument('--days',type=int,default=30)
    p.add_argument('--all-personal-records',action='store_true')
    p.add_argument('--prune-document-versions',action='store_true')
    p.add_argument('--keep-versions',type=int,default=2)
    p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    if a.env_file:
        from dotenv import load_dotenv
        if not Path(a.env_file).is_file():p.error('Environment file not found')
        load_dotenv(a.env_file,override=False)
    if not os.getenv('RAG_EVAL_TOKEN'):p.error('Set RAG_EVAL_TOKEN to your local user credential')
    from rag_app.security import Registry
    from rag_app.settings import open_store
    from rag_app.application_state import ApplicationState
    from rag_app.checkpoint import Checkpointer
    from rag_app.retention import Retention
    actor=Registry.from_file(os.getenv('RAG_AUTH_FILE','data/demo_auth.json')).authenticate('Bearer '+os.environ['RAG_EVAL_TOKEN'])
    store=open_store();state=ApplicationState(store)
    cp=Checkpointer(os.getenv('RAG_CHECKPOINT_DB','data/checkpoints.sqlite3'),store if store.backend=='postgresql' else None)
    result=Retention(state,cp).cleanup(actor,a.days,a.all_personal_records,not a.apply,a.prune_document_versions,a.keep_versions)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
