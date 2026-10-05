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
        with store.connect() as c:
            exists=c.execute("SELECT 1 FROM documents WHERE document_id=? LIMIT 1",(doc["document_id"],)).fetchone()
        if not exists:
            text,locations=parse_file(ROOT/"data/synthetic"/doc["file"])
            store.upsert(doc,text,locations)
    with store.connect() as c:
        c.execute("INSERT OR IGNORE INTO tickets VALUES ('T1001','demo','alice','open')")
        c.execute("INSERT OR IGNORE INTO tickets VALUES ('T1002','demo','bob','resolved')")

def main():
    store=Store(os.getenv("RAG_DB",str(ROOT/"data/rag.sqlite3")))
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

