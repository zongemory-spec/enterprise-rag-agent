from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
from rag_app.security import AccessError

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
 document_id TEXT NOT NULL, version INTEGER NOT NULL, title TEXT NOT NULL,
 source TEXT NOT NULL, hash TEXT NOT NULL, tenant_id TEXT NOT NULL, owner TEXT NOT NULL,
 allowed_groups TEXT NOT NULL, active INTEGER NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(document_id,version));
CREATE TABLE IF NOT EXISTS chunks (
 chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, version INTEGER NOT NULL,
 location TEXT NOT NULL, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
 run_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, actor TEXT NOT NULL,
 chunk_ids TEXT NOT NULL, metadata TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tickets (
 ticket_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, actor TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
 request_id TEXT PRIMARY KEY, status INTEGER NOT NULL, reason TEXT NOT NULL, created TEXT NOT NULL);
INSERT OR IGNORE INTO metadata VALUES ('index_version','0');
PRAGMA user_version=1;
"""
SELECT = """SELECT c.*,d.title,d.source,d.tenant_id,d.allowed_groups,d.owner,d.created_at,d.hash
FROM chunks c JOIN documents d ON c.document_id=d.document_id AND c.version=d.version
WHERE d.active=1 AND d.tenant_id=?
AND (d.owner=? OR EXISTS (
 SELECT 1 FROM json_each(d.allowed_groups) g WHERE g.value IN (SELECT value FROM json_each(?))
))"""

def split_text(text, max_chars=500):
    """Stable line spans; PDFs are converted page-by-page by ingest.parse_file."""
    chunks, buffer, start, end = [], "", 1, 1
    for line_no,line in enumerate(text.splitlines(),1):
        for offset in range(0,max(len(line),1),max_chars):
            part = line[offset:offset+max_chars]
            if buffer and len(buffer)+len(part)+1 > max_chars:
                chunks.append((f"lines {start}-{end}",buffer.strip()))
                buffer, start = "", line_no
            if not buffer:
                start=line_no
            buffer += part+"\n";end=line_no
    if buffer.strip():
        chunks.append((f"lines {start}-{end}",buffer.strip()))
    return chunks

class Store:
    def __init__(self,path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            if c.execute("PRAGMA user_version").fetchone()[0] not in (0,1):
                raise ValueError("Unsupported schema version")
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=5);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()

    @property
    def index_version(self):
        with self.connect() as c:
            return c.execute("SELECT value FROM metadata WHERE key='index_version'").fetchone()[0]

    def upsert(self,doc,text,locations=None):
        # This is a trusted local ingestion API, never an unauthenticated HTTP write endpoint.
        required={"document_id","version","title","source","tenant_id","owner","allowed_groups","created_at"}
        if not required <= doc.keys() or type(doc["version"]) is not int or doc["version"]<1:
            raise ValueError("Invalid document metadata")
        if not isinstance(doc["allowed_groups"],list) or not all(type(g) is str for g in doc["allowed_groups"]):
            raise ValueError("Invalid ACL")
        digest=hashlib.sha256(text.encode()).hexdigest()
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            latest=c.execute("SELECT * FROM documents WHERE document_id=? ORDER BY version DESC LIMIT 1",(doc["document_id"],)).fetchone()
            if latest:
                if latest["tenant_id"] != doc["tenant_id"]:
                    raise ValueError("Document IDs are globally unique; cannot move a document between tenants")
                if doc["version"] <= latest["version"]:
                    metadata_same = all(doc[k]==latest[k] for k in ("title","source","owner","created_at"))
                    acl_same = doc["allowed_groups"]==json.loads(latest["allowed_groups"])
                    if doc["version"]==latest["version"] and digest==latest["hash"] and metadata_same and acl_same and latest["active"]:
                        return False
                    raise ValueError("Updates, ACL changes and reactivation require a strictly newer version")
            c.execute("UPDATE documents SET active=0 WHERE document_id=?",(doc["document_id"],))
            c.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (doc["document_id"],doc["version"],doc["title"],doc["source"],digest,doc["tenant_id"],doc["owner"],
                       json.dumps(doc["allowed_groups"]),1,doc["created_at"]))
            for n,(location,part) in enumerate(locations or split_text(text)):
                chunk_id=hashlib.sha256(f"{doc['document_id']}:{doc['version']}:{n}:{digest}".encode()).hexdigest()[:24]
                c.execute("INSERT INTO chunks VALUES (?,?,?,?,?)",(chunk_id,doc["document_id"],doc["version"],location,part))
            c.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='index_version'")
        return True

    def deactivate(self,doc_id):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("UPDATE documents SET active=0 WHERE document_id=?",(doc_id,))
            c.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='index_version'")

    def authorized_chunks(self,actor):
        with self.connect() as c:
            return [dict(r) for r in c.execute(SELECT,(actor.tenant_id,actor.user_id,json.dumps(["public",*actor.groups])))]

    def citation(self,chunk_id,actor):
        with self.connect() as c:
            row=c.execute(SELECT+" AND c.chunk_id=?",(actor.tenant_id,actor.user_id,json.dumps(["public",*actor.groups]),chunk_id)).fetchone()
        if row is None:
            raise AccessError("citation_unavailable",404)
        return dict(row)

    def snapshot_all(self):
        with self.connect() as c:
            c.execute("BEGIN")
            version=c.execute("SELECT value FROM metadata WHERE key='index_version'").fetchone()[0]
            rows=[dict(r) for r in c.execute("""SELECT c.*,d.title,d.source,d.tenant_id,d.owner,d.allowed_groups
                FROM chunks c JOIN documents d ON c.document_id=d.document_id AND c.version=d.version WHERE d.active=1""")]
        return version,rows

    def save_run(self,run_id,actor,chunk_ids,metadata):
        with self.connect() as c:
            c.execute("INSERT INTO runs VALUES (?,?,?,?,?)",(run_id,actor.tenant_id,actor.user_id,json.dumps(chunk_ids),json.dumps(metadata)))
        # Deliberately store no question, answer, document text or raw model trace.

    def run(self,run_id,actor):
        with self.connect() as c:
            row=c.execute("SELECT * FROM runs WHERE run_id=?",(run_id,)).fetchone()
        if row is None:raise AccessError("run_not_found",404)
        if (row["tenant"],row["actor"]) != (actor.tenant_id,actor.user_id):raise AccessError("run_access_denied")
        ids=json.loads(row["chunk_ids"])
        visible=[]
        for cid in ids:
            try:self.citation(cid,actor);visible.append(cid)
            except AccessError:pass
        return {"run_id":run_id,"chunk_ids":visible,"metadata":json.loads(row["metadata"]),"redacted_chunks":len(ids)-len(visible)}

    def ticket(self,ticket_id,actor):
        with self.connect() as c:
            row=c.execute("SELECT status FROM tickets WHERE ticket_id=? AND tenant=? AND actor=?",(ticket_id,actor.tenant_id,actor.user_id)).fetchone()
        if row is None:raise AccessError("ticket_unavailable",404)
        return {"ticket_id":ticket_id,"status":row["status"]}

    def audit(self,request_id,status,reason):
        with self.connect() as c:
            c.execute("INSERT INTO audit VALUES (?,?,?,?)",(request_id,status,reason,datetime.now(timezone.utc).isoformat()))

