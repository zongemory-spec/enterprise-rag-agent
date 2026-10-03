import json
import os
from pathlib import Path
import secrets
from rag_app.ingest import parse_file
from rag_app.store import Store
ROOT=Path(__file__).resolve().parent

def populate(store):
    manifest=json.loads((ROOT/"data/synthetic/manifest.json").read_text(encoding="utf-8"))
    for doc in manifest:
        # On restart preserve administrative revocations and updates.
        exists=store.exists(doc["document_id"])
        if not exists:
            text,locations=parse_file(ROOT/"data/synthetic"/doc["file"])
            store.upsert(doc,text,locations)
    store.seed_ticket("T1001","demo","alice","open")
    store.seed_ticket("T1002","demo","bob","resolved")

def main():
    from rag_app.settings import open_store
    store=open_store()
    populate(store)
    path=Path(os.getenv("RAG_AUTH_FILE",str(ROOT/"data/demo_auth.json")))
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        rows=[{"user_id":uid,"tenant_id":tenant,"groups":groups,"token":secrets.token_urlsafe(32)}
              for uid,tenant,groups in [("alice","demo",["support"]),("bob","demo",["engineering"]),("alice","other",["support"])]]
        with path.open("x",encoding="utf-8") as f:json.dump(rows,f,indent=2)
        try:path.chmod(0o600)
        except OSError:pass
    print("Synthetic documents initialized; credentials stored privately, not printed.")
if __name__=="__main__":main()

