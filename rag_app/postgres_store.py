"""Authoritative PostgreSQL store; all business state lives here when selected."""
from contextlib import contextmanager
from datetime import datetime,timezone
import hashlib,json,re
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from rag_app.security import AccessError
from rag_app.store import split_text

SCHEMA="""
CREATE TABLE IF NOT EXISTS documents(document_id text NOT NULL,version integer NOT NULL,title text NOT NULL,source text NOT NULL,hash text NOT NULL,tenant_id text NOT NULL,owner text NOT NULL,allowed_groups jsonb NOT NULL,active integer NOT NULL,created_at text NOT NULL,PRIMARY KEY(document_id,version));
CREATE TABLE IF NOT EXISTS chunks(chunk_id text PRIMARY KEY,document_id text NOT NULL,version integer NOT NULL,location text NOT NULL,text text NOT NULL,FOREIGN KEY(document_id,version) REFERENCES documents(document_id,version));
CREATE TABLE IF NOT EXISTS metadata(key text PRIMARY KEY,value text NOT NULL);
INSERT INTO metadata VALUES ('index_version','0') ON CONFLICT DO NOTHING;
INSERT INTO metadata VALUES ('schema_version','2') ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS runs(run_id text PRIMARY KEY,tenant text NOT NULL,actor text NOT NULL,chunk_ids jsonb NOT NULL,metadata jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS tickets(ticket_id text PRIMARY KEY,tenant text NOT NULL,actor text NOT NULL,status text NOT NULL);
CREATE TABLE IF NOT EXISTS audit(request_id text PRIMARY KEY,status integer NOT NULL,reason text NOT NULL,created text NOT NULL);
"""
SELECT="""SELECT c.*,d.title,d.source,d.tenant_id,d.allowed_groups,d.owner,d.created_at,d.hash
FROM chunks c JOIN documents d USING(document_id,version)
WHERE d.active=1 AND d.tenant_id=%s AND (d.owner=%s OR EXISTS(
SELECT 1 FROM jsonb_array_elements_text(d.allowed_groups) g WHERE g=ANY(%s)))"""
class PostgresStore:
    backend="postgresql"
    def __init__(self,dsn,schema="rag_v2"):
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,50}",schema):raise ValueError("Invalid schema")
        self.dsn,self.schema=dsn,schema
        with psycopg.connect(dsn,connect_timeout=5) as c:
            c.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
        with self.connect() as c:
            c.execute(SCHEMA)
            if c.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()["value"]!="2":raise ValueError("Unsupported schema")
    @contextmanager
    def connect(self):
        with psycopg.connect(self.dsn,connect_timeout=5,row_factory=dict_row,options="-c statement_timeout=10000") as c:
            c.execute(sql.SQL("SET search_path TO {},public").format(sql.Identifier(self.schema)))
            yield c
    @property
    def index_version(self):
        with self.connect() as c:return c.execute("SELECT value FROM metadata WHERE key='index_version'").fetchone()["value"]
    def exists(self,doc_id):
        with self.connect() as c:return c.execute("SELECT 1 FROM documents WHERE document_id=%s LIMIT 1",(doc_id,)).fetchone() is not None
    def seed_ticket(self,*args):
        with self.connect() as c:c.execute("INSERT INTO tickets VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",args)
    def upsert(self,doc,text,locations=None):
        required={"document_id","version","title","source","tenant_id","owner","allowed_groups","created_at"}
        if not required<=doc.keys() or type(doc["version"]) is not int or doc["version"]<1:raise ValueError("Invalid metadata")
        if not isinstance(doc["allowed_groups"],list) or not all(type(g) is str for g in doc["allowed_groups"]):raise ValueError("Invalid ACL")
        digest=hashlib.sha256(text.encode()).hexdigest()
        with self.connect() as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext(current_schema()),27183)")
            old=c.execute("SELECT * FROM documents WHERE document_id=%s ORDER BY version DESC LIMIT 1",(doc["document_id"],)).fetchone()
            if old:
                if old["tenant_id"]!=doc["tenant_id"]:raise ValueError("Cannot move documents between tenants")
                if doc["version"]<=old["version"]:
                    same=all(doc[k]==old[k] for k in ("title","source","owner","created_at","allowed_groups"))
                    if doc["version"]==old["version"] and digest==old["hash"] and same and old["active"]:return False
                    raise ValueError("A strictly newer version is required")
            c.execute("UPDATE documents SET active=0 WHERE document_id=%s",(doc["document_id"],))
            c.execute("INSERT INTO documents VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,1,%s)",(doc["document_id"],doc["version"],doc["title"],doc["source"],digest,doc["tenant_id"],doc["owner"],json.dumps(doc["allowed_groups"]),doc["created_at"]))
            for n,(loc,part) in enumerate(locations or split_text(text)):
                cid=hashlib.sha256(f"{doc['document_id']}:{doc['version']}:{n}:{digest}".encode()).hexdigest()[:24]
                c.execute("INSERT INTO chunks VALUES (%s,%s,%s,%s,%s)",(cid,doc["document_id"],doc["version"],loc,part))
            c.execute("UPDATE metadata SET value=(value::bigint+1)::text WHERE key='index_version'")
        return True
    def deactivate(self,doc_id):
        with self.connect() as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext(current_schema()),27183)")
            c.execute("UPDATE documents SET active=0 WHERE document_id=%s",(doc_id,))
            c.execute("UPDATE metadata SET value=(value::bigint+1)::text WHERE key='index_version'")
    @staticmethod
    def scope(actor):return actor.tenant_id,actor.user_id,["public",*actor.groups]
    def authorized_chunks(self,actor):
        with self.connect() as c:return c.execute(SELECT,self.scope(actor)).fetchall()
    def citation(self,cid,actor):
        with self.connect() as c:row=c.execute(SELECT+" AND c.chunk_id=%s",(*self.scope(actor),cid)).fetchone()
        if row is None:raise AccessError("citation_unavailable",404)
        return row
    def snapshot_all(self):
        with self.connect() as c:
            rows=c.execute("""SELECT c.*,d.title,d.source,d.tenant_id,d.owner,d.allowed_groups,m.value AS generation
            FROM metadata m LEFT JOIN (chunks c JOIN documents d USING(document_id,version)) ON d.active=1
            WHERE m.key='index_version'""").fetchall()
        return rows[0]["generation"],[{k:v for k,v in r.items() if k!="generation"} for r in rows if r["chunk_id"] is not None]
    def save_run(self,run_id,actor,chunk_ids,metadata):
        with self.connect() as c:c.execute("INSERT INTO runs VALUES (%s,%s,%s,%s::jsonb,%s::jsonb)",(run_id,actor.tenant_id,actor.user_id,json.dumps(chunk_ids),json.dumps(metadata)))
    def run(self,run_id,actor):
        with self.connect() as c:r=c.execute("SELECT * FROM runs WHERE run_id=%s",(run_id,)).fetchone()
        if r is None:raise AccessError("run_not_found",404)
        if (r["tenant"],r["actor"])!=(actor.tenant_id,actor.user_id):raise AccessError("run_access_denied")
        visible=[]
        for cid in r["chunk_ids"]:
            try:self.citation(cid,actor);visible.append(cid)
            except AccessError:pass
        return {"run_id":run_id,"chunk_ids":visible,"metadata":r["metadata"],"redacted_chunks":len(r["chunk_ids"])-len(visible)}
    def ticket(self,ticket_id,actor):
        with self.connect() as c:r=c.execute("SELECT status FROM tickets WHERE ticket_id=%s AND tenant=%s AND actor=%s",(ticket_id,actor.tenant_id,actor.user_id)).fetchone()
        if r is None:raise AccessError("ticket_unavailable",404)
        return {"ticket_id":ticket_id,"status":r["status"]}
    def audit(self,request_id,status,reason):
        with self.connect() as c:c.execute("INSERT INTO audit VALUES (%s,%s,%s,%s)",(request_id,status,reason,datetime.now(timezone.utc).isoformat()))

