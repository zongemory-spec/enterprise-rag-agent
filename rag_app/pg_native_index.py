"""Native pgvector joins the authoritative PostgreSQL ACL and version tables."""
import json
from rag_app.retrieval import embed,MODEL_ID
from rag_app.security import AccessError
class NativePGIndex:
    def __init__(self,store,embedder=None):
        self.store,self.embedder=store,embedder
        self.model_id=embedder.model_id if embedder else MODEL_ID
        with store.connect() as c:
            c.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            c.execute("""CREATE TABLE IF NOT EXISTS embeddings(chunk_id text NOT NULL REFERENCES chunks(chunk_id),model_id text NOT NULL,generation text NOT NULL,embedding vector NOT NULL,PRIMARY KEY(chunk_id,model_id))""")
    def vectors(self,texts):
        return self.embedder.embed(texts) if self.embedder else [embed(t) for t in texts]
    def sync(self,store=None):
        store=store or self.store
        generation,rows=store.snapshot_all()
        vectors=self.vectors([r["title"]+" "+r["text"] for r in rows])
        if len(vectors)!=len(rows):raise ValueError("Embedding count mismatch")
        with store.connect() as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext(current_schema()),27183)")
            if c.execute("SELECT value FROM metadata WHERE key='index_version'").fetchone()["value"]!=generation:raise AccessError("index_changed_retry",409)
            c.execute("DELETE FROM embeddings WHERE model_id=%s",(self.model_id,))
            for row,v in zip(rows,vectors):c.execute("INSERT INTO embeddings VALUES (%s,%s,%s,%s::vector)",(row["chunk_id"],self.model_id,generation,json.dumps(v)))
        return len(rows)
    def status(self):
        generation=self.store.index_version
        with self.store.connect() as c:
            expected=c.execute('SELECT COUNT(*) AS n FROM chunks c JOIN documents d USING(document_id,version) WHERE d.active=1').fetchone()['n']
            indexed=c.execute('SELECT COUNT(*) AS n FROM embeddings e JOIN chunks c USING(chunk_id) JOIN documents d USING(document_id,version) WHERE e.model_id=%s AND e.generation=%s AND d.active=1',(self.model_id,generation)).fetchone()['n']
        return {'model_id':self.model_id,'kind':'semantic' if self.embedder else 'lexical-hash','expected_chunks':expected,'indexed_chunks':indexed,'ready':expected>0 and indexed==expected,'index_version':generation}
    def retrieve(self,store,actor,query,top_k=4):
        if not self.status()['ready']:raise AccessError('vector_index_not_ready_rebuild_required',409)
        generation=store.index_version;v=json.dumps(self.vectors([query])[0])
        with store.connect() as c:
            rows=c.execute("""SELECT c.chunk_id,1-(e.embedding <=> %s::vector) AS score
            FROM embeddings e JOIN chunks c USING(chunk_id) JOIN documents d USING(document_id,version)
            WHERE e.model_id=%s AND e.generation=%s AND d.active=1 AND d.tenant_id=%s
            AND (d.owner=%s OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(d.allowed_groups) g WHERE g=ANY(%s)))
            ORDER BY e.embedding <=> %s::vector,c.chunk_id LIMIT %s""",(v,self.model_id,generation,actor.tenant_id,actor.user_id,["public",*actor.groups],v,top_k)).fetchall()
        result=[]
        for r in rows:
            if r["score"]>=.15:
                try:result.append(dict(store.citation(r["chunk_id"],actor),score=float(r["score"])))
                except AccessError:pass
        if store.index_version!=generation:raise AccessError("index_changed_retry",409)
        return result

